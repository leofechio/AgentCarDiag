#!/usr/bin/env python3
"""
AgentCarDiag — Hardware Simulator
Simulates an ESP32-S3 node sending realistic vehicle telemetry to /ws/hardware.

Usage:
  python test_simulator.py [--host HOST] [--port PORT] [--can-rate N] [--osc-interval S]

Simulated data:
  • CAN frames: RPM (0x120), Speed (0x201), Engine Temp (0x310), generic frames
  • ADC burst:  500 samples of a CKP-like inductive sensor signal (sinusoidal pulse)
"""

import asyncio
import json
import math
import random
import signal
import sys
import time
import argparse
from datetime import datetime, timezone

try:
    import websockets
except ImportError:
    print("ERROR: 'websockets' not installed. Run: pip install websockets")
    sys.exit(1)


# ─── ANSI colors ───────────────────────────────────────────────────────────────

class C:
    RESET  = '\033[0m'
    BOLD   = '\033[1m'
    CYAN   = '\033[96m'
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    RED    = '\033[91m'
    MAGENTA= '\033[95m'
    DIM    = '\033[2m'


def log(level: str, msg: str):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    colors = {
        'INFO':  C.CYAN,
        'OK':    C.GREEN,
        'WARN':  C.YELLOW,
        'ERROR': C.RED,
        'DATA':  C.MAGENTA,
    }
    color = colors.get(level, C.RESET)
    print(f"{C.DIM}{ts}{C.RESET} {color}{level:5s}{C.RESET}  {msg}")


# ─── Vehicle state model ────────────────────────────────────────────────────────

class VehicleModel:
    """Simulates realistic automotive sensor values over time."""

    def __init__(self):
        self.t = 0.0         # simulation time in seconds
        self.rpm = 800.0     # idle RPM
        self.speed = 0.0     # km/h
        self.temp = 25.0     # °C coolant temp
        self.throttle = 0.0  # 0–1

    def tick(self, dt: float = 0.1):
        self.t += dt

        # Simulate throttle input — slow ramps with randomness
        target_throttle = 0.5 + 0.45 * math.sin(self.t * 0.3) + random.gauss(0, 0.05)
        target_throttle = max(0.0, min(1.0, target_throttle))
        self.throttle += (target_throttle - self.throttle) * 0.15

        # RPM: idle at 800, max ~6500 under full throttle
        target_rpm = 800 + self.throttle * 5700 + random.gauss(0, 30)
        self.rpm += (target_rpm - self.rpm) * 0.08
        self.rpm = max(500, min(8000, self.rpm))

        # Speed follows RPM with lag (simulates gear ratio)
        target_speed = self.rpm * 0.018 + random.gauss(0, 0.5)
        self.speed += (target_speed - self.speed) * 0.04
        self.speed = max(0, min(250, self.speed))

        # Engine temp: warms up from ambient, stabilizes ~90°C
        target_temp = 90 + self.throttle * 10 + random.gauss(0, 0.3)
        self.temp += (target_temp - self.temp) * 0.002

    def rpm_bytes(self) -> list[int]:
        """Encode RPM as 2 bytes big-endian (× 4 for raw CAN convention)."""
        raw = int(self.rpm * 4) & 0xFFFF
        return [0x00, 0x00, (raw >> 8) & 0xFF, raw & 0xFF, 0x00, 0x00, 0x00, 0x00]

    def speed_bytes(self) -> list[int]:
        """Encode speed as 2 bytes big-endian (× 100 for 0.01 km/h resolution)."""
        raw = int(self.speed * 100) & 0xFFFF
        return [0x00, (raw >> 8) & 0xFF, raw & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00]

    def temp_bytes(self) -> list[int]:
        """Encode temp: value + 40 offset (common CAN convention)."""
        raw = int(self.temp + 40) & 0xFF
        return [raw, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]


# ─── ADC / Oscilloscope signal generator ───────────────────────────────────────

class CKPSignalGenerator:
    """
    Simulates a CKP (Crankshaft Position) inductive sensor.
    Outputs a 58-tooth pulse pattern (60-2 wheel) as a pulsating sine wave.
    """

    def __init__(self, sample_rate: int = 10_000):
        self.sample_rate = sample_rate
        self.phase = 0.0

    def generate_burst(self, n_samples: int, rpm: float) -> list[float]:
        """
        Generate n_samples of CKP-like signal.
        Frequency of pulse = RPM/60 * 58 (for 60-2 crank wheel).
        """
        samples = []
        teeth = 58
        freq_base = (rpm / 60.0) * teeth     # pulse frequency in Hz
        dt = 1.0 / self.sample_rate

        for i in range(n_samples):
            t = i * dt

            # Fundamental frequency (main tooth signal)
            sine_main = math.sin(2 * math.pi * freq_base * t + self.phase)

            # 2nd harmonic (typical inductive sensor behavior)
            sine_2h = 0.3 * math.sin(4 * math.pi * freq_base * t + self.phase)

            # Amplitude envelope pulsing (simulates cylinder firings)
            amp = 0.8 + 0.2 * math.sin(2 * math.pi * (freq_base / teeth) * t)

            # Noise
            noise = random.gauss(0, 0.02)

            # Combine and scale to 0–3.3V
            raw = amp * (sine_main + sine_2h) + noise
            volt = (raw + 1.4) / 2.8 * 3.3
            volt = max(0.0, min(3.3, volt))
            samples.append(round(volt, 4))

        self.phase += 2 * math.pi * freq_base * n_samples * dt
        self.phase %= (2 * math.pi)

        return samples


# ─── Simulator core ─────────────────────────────────────────────────────────────

class Simulator:

    GENERIC_IDS = [0x100, 0x180, 0x280, 0x300, 0x400, 0x500, 0x600, 0x700]

    def __init__(self, uri: str, can_rate: float, osc_interval: float):
        self.uri = uri
        self.can_rate = can_rate           # frames per second
        self.osc_interval = osc_interval   # seconds between ADC bursts
        self.vehicle = VehicleModel()
        self.ckp = CKPSignalGenerator(sample_rate=10_000)
        self.running = True
        self.frames_sent = 0
        self.bursts_sent = 0

    def utc_ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def make_can_frame(self, can_id: int, data: list[int]) -> str:
        dlc = min(len(data), 8)
        return json.dumps({
            "type":  "can_frame",
            "id":    f"0x{can_id:03X}",
            "dlc":   dlc,
            "data":  data[:dlc],
            "ts":    self.utc_ts(),
        }, separators=(',', ':'))

    def make_adc_burst(self, samples: list[float]) -> str:
        return json.dumps({
            "type":        "adc_burst",
            "samples":     samples,
            "sample_rate": self.ckp.sample_rate,
            "n_samples":   len(samples),
            "ts":          self.utc_ts(),
        }, separators=(',', ':'))

    async def run(self):
        backoff = 1.0

        while self.running:
            try:
                log('INFO', f"Conectando em {C.BOLD}{self.uri}{C.RESET}…")
                async with websockets.connect(
                    self.uri,
                    ping_interval=15,
                    ping_timeout=10,
                    open_timeout=10,
                ) as ws:
                    backoff = 1.0
                    log('OK',   f"Conectado! Iniciando simulação CAN {self.can_rate} fps | OSC a cada {self.osc_interval}s")
                    await asyncio.gather(
                        self.can_loop(ws),
                        self.osc_loop(ws),
                        self.stats_loop(),
                        self.listen_commands(ws),
                    )

            except websockets.exceptions.ConnectionClosedOK:
                log('WARN', "Conexão fechada normalmente. Reconectando…")
            except websockets.exceptions.ConnectionClosedError as e:
                log('WARN', f"Conexão fechada com erro: {e}. Reconectando em {backoff:.1f}s…")
            except (OSError, ConnectionRefusedError) as e:
                log('ERROR', f"Falha de conexão: {e}. Tentando novamente em {backoff:.1f}s…")
            except Exception as e:
                log('ERROR', f"Erro inesperado: {e}")

            if not self.running:
                break

            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 30.0)

    async def can_loop(self, ws):
        """Continuously send CAN frames at the configured rate."""
        interval = 1.0 / self.can_rate

        while self.running:
            self.vehicle.tick(dt=interval)
            v = self.vehicle

            # Primary automotive frames
            frames = [
                self.make_can_frame(0x120, v.rpm_bytes()),    # Engine RPM
                self.make_can_frame(0x201, v.speed_bytes()),   # Vehicle Speed
                self.make_can_frame(0x310, v.temp_bytes()),    # Coolant Temp
            ]

            # Occasional random frames (simulates other ECUs)
            if random.random() < 0.3:
                rand_id = random.choice(self.GENERIC_IDS)
                rand_data = [random.randint(0, 255) for _ in range(random.randint(1, 8))]
                frames.append(self.make_can_frame(rand_id, rand_data))

            for frame in frames:
                try:
                    await ws.send(frame)
                    self.frames_sent += 1
                except Exception:
                    return

            await asyncio.sleep(interval)

    async def osc_loop(self, ws):
        """Periodically send ADC burst (CKP signal simulation)."""
        while self.running:
            await asyncio.sleep(self.osc_interval)

            n = 500
            samples = self.ckp.generate_burst(n, self.vehicle.rpm)
            burst = self.make_adc_burst(samples)

            try:
                await ws.send(burst)
                self.bursts_sent += 1
                log('DATA', (
                    f"OSC burst #{self.bursts_sent}: {n} amostras | "
                    f"RPM={self.vehicle.rpm:.0f} | "
                    f"Vmin={min(samples):.3f}V Vmax={max(samples):.3f}V"
                ))
            except Exception:
                return

    async def stats_loop(self):
        """Print periodic statistics."""
        while self.running:
            await asyncio.sleep(5)
            v = self.vehicle
            log('INFO', (
                f"Stats → Frames: {C.CYAN}{self.frames_sent}{C.RESET} | "
                f"Bursts: {C.MAGENTA}{self.bursts_sent}{C.RESET} | "
                f"RPM: {C.GREEN}{v.rpm:.0f}{C.RESET} | "
                f"Speed: {C.GREEN}{v.speed:.1f} km/h{C.RESET} | "
                f"Temp: {C.YELLOW}{v.temp:.1f}°C{C.RESET}"
            ))

    async def listen_commands(self, ws):
        """Listen for control commands from the server (forwarded from web clients)."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
                cmd = msg.get('cmd', '')
                log('INFO', f"Comando recebido: {C.BOLD}{cmd}{C.RESET} → {msg}")
            except Exception:
                log('WARN', f"Mensagem não-JSON recebida: {raw[:60]}")

    def stop(self):
        self.running = False
        log('WARN', "Simulador encerrando…")


# ─── CLI entry point ───────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description='AgentCarDiag Hardware Simulator — envia telemetria fake para o servidor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python test_simulator.py
  python test_simulator.py --host 192.168.1.100 --port 8000
  python test_simulator.py --can-rate 20 --osc-interval 2
        """,
    )
    parser.add_argument('--host',         default='localhost',   help='Servidor host (default: localhost)')
    parser.add_argument('--port',         default=8000, type=int, help='Servidor porta (default: 8000)')
    parser.add_argument('--can-rate',     default=10.0, type=float, help='Frames CAN por segundo (default: 10)')
    parser.add_argument('--osc-interval', default=3.0,  type=float, help='Intervalo entre rajadas ADC em segundos (default: 3)')
    parser.add_argument('--node-id',      default='simulator-esp32s3', help='ID do nó hardware')
    return parser.parse_args()


async def main():
    args = parse_args()
    uri = f"ws://{args.host}:{args.port}/ws/hardware?node_id={args.node_id}"

    print(f"""
{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════════╗
║          AgentCarDiag — Hardware Simulator           ║
╚══════════════════════════════════════════════════════╝{C.RESET}
  Servidor   : {C.GREEN}{uri}{C.RESET}
  Node ID    : {C.CYAN}{args.node_id}{C.RESET}
  CAN rate   : {C.YELLOW}{args.can_rate} frames/s{C.RESET}
  OSC burst  : {C.MAGENTA}a cada {args.osc_interval}s (500 amostras){C.RESET}
  Pressione {C.BOLD}Ctrl+C{C.RESET} para encerrar
""")

    sim = Simulator(uri, args.can_rate, args.osc_interval)

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT,  sim.stop)
    loop.add_signal_handler(signal.SIGTERM, sim.stop)

    try:
        await sim.run()
    except asyncio.CancelledError:
        pass
    finally:
        log('OK', f"Simulação encerrada. Total: {sim.frames_sent} frames, {sim.bursts_sent} bursts OSC.")


if __name__ == '__main__':
    asyncio.run(main())
