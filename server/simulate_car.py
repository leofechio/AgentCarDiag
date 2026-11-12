#!/usr/bin/env python3
"""
AgentCarDiag — Emulador de Telemetria CAN (Virtual Car Node)
=============================================================
Simula um veículo real gerando tráfego CAN/OBD-II realista e transmite
via WebSocket Seguro (WSS) para o servidor de produção em:

    wss://diag.anality.me/ws/node/virtual_car_node

Fallback automático para ambiente local:

    ws://localhost:8000/ws/node/virtual_car_node

Uso:
    python simulate_car.py                          # produção (WSS)
    python simulate_car.py --local                  # localhost
    python simulate_car.py --rate 20                # 20 frames/s
    python simulate_car.py --url ws://host:8000/... # URL customizada

Variáveis de ambiente:
    CARDIAG_WS_URL   — sobrescreve a URL completamente
    CARDIAG_LOCAL=1  — força fallback para localhost

Dependências:
    pip install websockets
"""

import asyncio
import json
import math
import os
import random
import sys
import time
import argparse
from datetime import datetime, timezone

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print("❌ Instale a dependência: pip install websockets")
    sys.exit(1)

# ─── ANSI colors ──────────────────────────────────────────────────────────────

class C:
    RESET   = '\033[0m'
    BOLD    = '\033[1m'
    DIM     = '\033[2m'
    CYAN    = '\033[96m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    RED     = '\033[91m'
    MAGENTA = '\033[95m'
    BLUE    = '\033[94m'

def log(level: str, msg: str):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    colors = {
        'INFO':  C.CYAN,
        'OK':    C.GREEN,
        'WARN':  C.YELLOW,
        'ERROR': C.RED,
        'DATA':  C.MAGENTA,
        'CAN':   C.BLUE,
    }
    color = colors.get(level, C.RESET)
    print(f"{C.DIM}{ts}{C.RESET} {color}{level:5s}{C.RESET}  {msg}", flush=True)

# ─── Modelo de veículo ────────────────────────────────────────────────────────

class VehicleModel:
    """
    Modelo cinemático simples de um VW Passat.
    Simula variações contínuas realistas de RPM, velocidade e temperatura.
    """

    def __init__(self):
        self.t         = 0.0    # tempo de simulação (s)
        self.rpm       = 850.0  # rotações por minuto
        self.speed     = 0.0    # km/h
        self.temp      = 20.0   # temperatura do líquido de arrefecimento (°C)
        self.throttle  = 0.0    # posição do acelerador (0–1)
        self.brake     = 0.0    # posição do freio (0–1)
        self.ignition  = 1      # 1 = ligado, 0 = desligado
        self.gear      = 1      # marcha atual (estimada)

    def tick(self, dt: float = 0.05):
        self.t += dt

        # ── Acelerador: onda senoidal suave + ruído ──
        target_thr = 0.45 + 0.40 * math.sin(self.t * 0.25) \
                   + 0.10 * math.sin(self.t * 1.1) \
                   + random.gauss(0, 0.03)
        target_thr = max(0.0, min(1.0, target_thr))
        self.throttle += (target_thr - self.throttle) * 0.12

        # Freio oposto ao acelerador (simplificado)
        self.brake = max(0.0, min(1.0, (0.2 - self.throttle) * 2 + random.gauss(0, 0.02)))

        # ── RPM: 800 rpm em idle, até 4000 rpm em carga ──
        target_rpm = 800 + self.throttle * 3200 + random.gauss(0, 25)
        self.rpm  += (target_rpm - self.rpm) * 0.10
        self.rpm   = max(650, min(4000, self.rpm))

        # ── Velocidade com lag em relação à RPM ──
        target_speed = self.rpm * 0.032 + random.gauss(0, 0.3)
        self.speed  += (target_speed - self.speed) * 0.035
        self.speed   = max(0.0, min(140.0, self.speed))

        # ── Temperatura: aquece de ambiente até ~90 °C ──
        target_temp = 88 + self.throttle * 7 + random.gauss(0, 0.2)
        self.temp  += (target_temp - self.temp) * 0.0015
        self.temp   = max(20.0, min(105.0, self.temp))

        # ── Marcha estimada pela velocidade ──
        if   self.speed < 15:  self.gear = 1
        elif self.speed < 30:  self.gear = 2
        elif self.speed < 55:  self.gear = 3
        elif self.speed < 85:  self.gear = 4
        else:                  self.gear = 5

    # ── Encoders CAN ──────────────────────────────────────────────────────────

    def obd_rpm_bytes(self) -> list[int]:
        """0x7E8 PID 0x0C — RPM × 4 em 2 bytes big-endian."""
        raw = int(self.rpm * 4) & 0xFFFF
        return [0x04, 0x41, 0x0C, (raw >> 8) & 0xFF, raw & 0xFF, 0xAA, 0xAA, 0xAA]

    def obd_speed_bytes(self) -> list[int]:
        """0x7E8 PID 0x0D — Velocidade (km/h) em 1 byte."""
        spd = int(self.speed) & 0xFF
        return [0x03, 0x41, 0x0D, spd, 0xAA, 0xAA, 0xAA, 0xAA]

    def obd_temp_bytes(self) -> list[int]:
        """0x7E8 PID 0x05 — ECT: valor + 40 em 1 byte."""
        raw = int(self.temp + 40) & 0xFF
        return [0x03, 0x41, 0x05, raw, 0xAA, 0xAA, 0xAA, 0xAA]

    def pedal_bytes(self) -> list[int]:
        """0x280 — Posição do acelerador e freio (painel)."""
        thr_raw = int(self.throttle * 255) & 0xFF
        brk_raw = int(self.brake    * 255) & 0xFF
        return [thr_raw, brk_raw, 0x00, 0x00, self.ignition, self.gear, 0x00, 0x00]

    def dashboard_bytes(self) -> list[int]:
        """0x380 — Painel: velocidade + RPM baixo byte."""
        spd = int(self.speed) & 0xFF
        rpm_lo = int(self.rpm) & 0xFF
        return [spd, rpm_lo, int(self.temp) & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00]

    def status_bytes(self) -> list[int]:
        """0x420 — Status de ignição + marcha + flags."""
        return [self.ignition, self.gear, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]


# ─── Emulador principal ───────────────────────────────────────────────────────

class VirtualCarNode:
    """
    Nó virtual que emula um ECU conectado ao servidor AgentCarDiag.
    Conecta via WSS, envia handshake, e produz tráfego CAN realista em loop.
    """

    PROD_URL  = "wss://diag.anality.me/ws/node/virtual_car_node"
    LOCAL_URL = "ws://localhost:8000/ws/node/virtual_car_node"

    def __init__(self, url: str, rate: float):
        self.url     = url
        self.rate    = rate          # frames por segundo
        self.vehicle = VehicleModel()
        self.running = True

        # Estatísticas
        self.frames_sent  = 0
        self.bytes_sent   = 0
        self.connect_attempts = 0
        self.started_at   = time.monotonic()

    def _ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _make_frame(self, can_id: int, data: list[int], extended: bool = False) -> str:
        """Serializa um frame CAN no formato esperado pelo backend."""
        dlc = min(len(data), 8)
        data_hex = ' '.join(f'{b:02X}' for b in data[:dlc])
        msg = {
            "type":      "can_frame",
            "id":        f"0x{can_id:03X}",
            "extended":  extended,
            "dlc":       dlc,
            "data":      data_hex,
            "timestamp": self._ts(),
        }
        return json.dumps(msg, separators=(',', ':'))

    def _make_handshake(self) -> str:
        return json.dumps({
            "type": "handshake",
            "node": "virtual_passat",
            "hw":   "SIMULATOR",
            "rate": self.rate,
            "fw":   "simulate_car.py/1.0",
        }, separators=(',', ':'))

    def _make_ping(self) -> str:
        elapsed = time.monotonic() - self.started_at
        return json.dumps({
            "type":        "ping",
            "node_id":     "virtual_passat",
            "uptime_s":    round(elapsed, 1),
            "frames_sent": self.frames_sent,
            "rpm":         round(self.vehicle.rpm, 1),
            "speed":       round(self.vehicle.speed, 1),
            "temp":        round(self.vehicle.temp, 1),
        }, separators=(',', ':'))

    async def _send(self, ws, payload: str) -> bool:
        """Envia payload e atualiza contadores. Retorna False em falha."""
        try:
            await ws.send(payload)
            self.frames_sent += 1
            self.bytes_sent  += len(payload.encode())
            return True
        except ConnectionClosed:
            return False
        except Exception as e:
            log('WARN', f"Erro ao enviar frame: {e}")
            return False

    async def _telemetry_loop(self, ws):
        """Loop principal de geração de telemetria CAN."""
        interval = 1.0 / self.rate
        last_ping = time.monotonic()
        last_stats = time.monotonic()

        while self.running:
            t0 = time.monotonic()
            self.vehicle.tick(dt=interval)
            v = self.vehicle

            # ── OBD-II (0x7E8): RPM, velocidade, temperatura ──
            frames = [
                self._make_frame(0x7E8, v.obd_rpm_bytes()),
                self._make_frame(0x7E8, v.obd_speed_bytes()),
                self._make_frame(0x7E8, v.obd_temp_bytes()),
            ]

            # ── Broadcast de conforto/painel ──
            frames += [
                self._make_frame(0x280, v.pedal_bytes()),
                self._make_frame(0x380, v.dashboard_bytes()),
                self._make_frame(0x420, v.status_bytes()),
            ]

            # ── Frames aleatórios de ECUs adicionais (~30 % do tempo) ──
            if random.random() < 0.30:
                rand_id   = random.choice([0x100, 0x180, 0x200, 0x300, 0x500, 0x600])
                rand_data = [random.randint(0, 0xFF) for _ in range(random.randint(2, 8))]
                frames.append(self._make_frame(rand_id, rand_data))

            for frame in frames:
                ok = await self._send(ws, frame)
                if not ok:
                    log('WARN', "Conexão perdida durante envio de frames")
                    return

            # ── Heartbeat a cada 10 s ──
            now = time.monotonic()
            if now - last_ping >= 10.0:
                last_ping = now
                ping_ok = await self._send(ws, self._make_ping())
                if not ping_ok:
                    return
                log('OK', (
                    f"♥ ping | RPM={v.rpm:.0f} | "
                    f"speed={v.speed:.1f}km/h | "
                    f"temp={v.temp:.1f}°C | "
                    f"frames={self.frames_sent}"
                ))

            # ── Estatísticas a cada 5 s ──
            if now - last_stats >= 5.0:
                last_stats = now
                kb = self.bytes_sent / 1024
                log('DATA', (
                    f"Frames: {C.CYAN}{self.frames_sent}{C.RESET} | "
                    f"Dados: {C.CYAN}{kb:.1f} KB{C.RESET} | "
                    f"RPM: {C.GREEN}{v.rpm:.0f}{C.RESET} | "
                    f"Speed: {C.GREEN}{v.speed:.1f} km/h{C.RESET} | "
                    f"Temp: {C.YELLOW}{v.temp:.1f}°C{C.RESET} | "
                    f"Gear: {v.gear}"
                ))

            # ── Controle de taxa (compensar tempo gasto no envio) ──
            elapsed = time.monotonic() - t0
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def _listen_server(self, ws):
        """Recebe e responde comandos UDS e de controle do servidor."""
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    log('INFO', f"Servidor → {msg}")
                    cmd = msg.get("cmd", "")

                    # Simula respostas positivas UDS para rotinas de oficina e testes
                    if cmd == "obd_send" or cmd == "raw_can":
                        query = msg.get("query", "")
                        header = msg.get("header", "7E0")
                        resp_id = hex(int(header, 16) + 8) if header.isalnum() else "0x7E8"

                        # Se for UDS Routine Control ou Diagnostic Session
                        if query.startswith("1003"): # Extended Session
                            resp_data = [2, 0x50, 0x03, 0x00, 0x32, 0x01, 0xF4, 0xAA]
                            await ws.send(json.dumps({"type": "can_frame", "id": resp_id, "dlc": 8, "data": resp_data}))
                            log('OK', f"UDS Resposta Sessão Estendida (0x50 03) → {resp_id}")
                        elif query.startswith("3101"): # Routine Control Start
                            sub = int(query[4:6], 16) if len(query) >= 6 else 0x01
                            resp_data = [4, 0x71, 0x01, sub, 0x00, 0xAA, 0xAA, 0xAA]
                            await ws.send(json.dumps({"type": "can_frame", "id": resp_id, "dlc": 8, "data": resp_data}))
                            log('OK', f"UDS Resposta Rotina Confirmada (0x71 01 {sub:02X}) → {resp_id}")
                        elif query.startswith("14"): # Clear DTCs
                            resp_data = [1, 0x54, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
                            await ws.send(json.dumps({"type": "can_frame", "id": resp_id, "dlc": 8, "data": resp_data}))
                            log('OK', f"UDS DTCs Apagados (0x54) → {resp_id}")
                except Exception as e:
                    log('WARN', f"Erro processando mensagem do servidor: {e}")
        except ConnectionClosed:
            pass

    async def run(self):
        """Loop de conexão com backoff exponencial."""
        backoff = 1.0

        while self.running:
            self.connect_attempts += 1
            log('INFO', f"[#{self.connect_attempts}] Conectando em {C.BOLD}{self.url}{C.RESET}…")

            try:
                # SSL automático para wss://, sem SSL para ws://
                extra_kwargs = {}
                if self.url.startswith("wss://"):
                    import ssl
                    ssl_ctx = ssl.create_default_context()
                    extra_kwargs["ssl"] = ssl_ctx

                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=15,
                    open_timeout=12,
                    **extra_kwargs,
                ) as ws:
                    backoff = 1.0
                    log('OK', f"✅ Conectado! Enviando handshake…")

                    # Handshake inicial
                    await ws.send(self._make_handshake())

                    # Rodar telemetria e listener simultaneamente
                    await asyncio.gather(
                        self._telemetry_loop(ws),
                        self._listen_server(ws),
                    )

            except ConnectionClosed as e:
                log('WARN', f"Conexão fechada: {e}")
            except OSError as e:
                log('ERROR', f"Falha de rede: {e}")
            except Exception as e:
                log('ERROR', f"Erro inesperado: {type(e).__name__}: {e}")

            if not self.running:
                break

            log('WARN', f"Reconectando em {backoff:.1f}s…")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 30.0)

    def stop(self):
        self.running = False


# ─── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AgentCarDiag — Emulador de Telemetria CAN",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python simulate_car.py                    # WSS produção, 15 fps
  python simulate_car.py --local            # WS localhost:8000
  python simulate_car.py --rate 20          # 20 frames/s
  python simulate_car.py --url wss://...    # URL customizada

Variáveis de ambiente:
  CARDIAG_WS_URL=wss://...   URL completa (máxima prioridade)
  CARDIAG_LOCAL=1            força fallback para localhost
        """,
    )
    parser.add_argument(
        '--local', action='store_true',
        help='Usar localhost:8000 em vez do servidor de produção'
    )
    parser.add_argument(
        '--url', default=None,
        help='URL WebSocket customizada (sobrescreve tudo)'
    )
    parser.add_argument(
        '--rate', type=float, default=15.0,
        help='Frames CAN por segundo (default: 15, range: 1–50)'
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # Resolução da URL (prioridade: --url > env > --local > produção)
    env_url = os.environ.get('CARDIAG_WS_URL')
    env_local = os.environ.get('CARDIAG_LOCAL', '').strip() in ('1', 'true', 'yes')

    if args.url:
        url = args.url
    elif env_url:
        url = env_url
    elif args.local or env_local:
        url = VirtualCarNode.LOCAL_URL
    else:
        url = VirtualCarNode.PROD_URL

    rate = max(1.0, min(50.0, args.rate))

    print(f"""
{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════════╗
║     AgentCarDiag — Virtual Car Node (Simulator)      ║
╚══════════════════════════════════════════════════════╝{C.RESET}
  Servidor   : {C.GREEN}{url}{C.RESET}
  Taxa CAN   : {C.YELLOW}{rate} frames/s{C.RESET}
  Veículo    : {C.CYAN}VW Passat (virtual_passat){C.RESET}
  PIDs       : {C.DIM}OBD-II 0x7E8 (RPM/Speed/Temp) + 0x280/0x380/0x420{C.RESET}
  Pressione  : {C.BOLD}Ctrl+C{C.RESET} para encerrar
""")

    node = VirtualCarNode(url=url, rate=rate)

    loop = asyncio.get_event_loop()
    try:
        import signal
        loop.add_signal_handler(signal.SIGINT,  node.stop)
        loop.add_signal_handler(signal.SIGTERM, node.stop)
    except NotImplementedError:
        pass  # Windows não suporta add_signal_handler

    try:
        await node.run()
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        node.stop()
    finally:
        elapsed = time.monotonic() - node.started_at
        log('OK', (
            f"Encerrado. "
            f"Uptime: {elapsed:.0f}s | "
            f"Frames: {node.frames_sent} | "
            f"Dados: {node.bytes_sent / 1024:.1f} KB | "
            f"Tentativas de conexão: {node.connect_attempts}"
        ))


if __name__ == '__main__':
    asyncio.run(main())
