#!/usr/bin/env python3
"""
hantek_cli.py — CLI e Ponte WebSocket em Tempo Real para Osciloscópio Automotivo Hantek 1008C (USB 0783:5725)
Projeto AgentCarDiag

Exemplos de uso:
  1. Verificar conexão, autocalibrar 8 canais e capturar 1 janela Burst:
     python hantek_tools/hantek_cli.py --capture

  2. Capturar com ponta atenuadora 20:1 (HT201 para Injetores/Primário Ignição) no CH1:
     python hantek_tools/hantek_cli.py --capture --ch 1 2 --atten 20 1 --ns-div 1000000

  3. Transmitir em tempo real para o Dashboard Web do AgentCarDiag (aba Osciloscópio):
     python hantek_tools/hantek_cli.py --ws ws://127.0.0.1:8000/ws/hardware --ch 1 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hantek1008_driver import Hantek1008C

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "server" / "data" / "cardiag.db"


def persist_capture_to_sqlite(
    ch1_samples: List[float],
    ch2_samples: List[float],
    sample_rate_hz: float,
    metrics_ch1: dict,
) -> Optional[int]:
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute("SELECT id FROM sessions WHERE is_active = 1 LIMIT 1").fetchone()
        session_id = row[0] if row else "hantek_1008c_session"
        now_iso = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO osc_captures (
                session_id, timestamp, channel, sample_rate,
                samples_json, ch2_samples_json, vmin, vmax, vmean
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                now_iso,
                1,
                int(sample_rate_hz),
                json.dumps(ch1_samples[:512]),
                json.dumps(ch2_samples[:512]),
                metrics_ch1["vmin"],
                metrics_ch1["vmax"],
                metrics_ch1["vmean"],
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return row_id
    except Exception:
        return None


def run_cli_capture(
    channels_1based: List[int],
    ns_per_div: int,
    vscale: float,
    attenuations: List[float],
    out_json: Optional[str] = None,
    calibrate_all: bool = False,
) -> int:
    active_0based = [max(0, min(7, c - 1)) for c in channels_1based]
    atten_map = [1.0] * 8
    for idx, ch0 in enumerate(active_0based):
        if idx < len(attenuations):
            atten_map[ch0] = attenuations[idx]

    print(f"🔌 Conectando ao Osciloscópio Automotivo Hantek 1008C (USB 0783:5725)...")
    scope = Hantek1008C(
        ns_per_div=ns_per_div,
        vertical_scale_factor=vscale,
        active_channels=active_0based,
        probe_attenuation=atten_map,
    )
    scope.connect()
    try:
        t0 = time.time()
        scope.init(calibrate_all_scales=calibrate_all)
        init_dt = time.time() - t0
        sr_hz = scope.get_effective_sample_rate_hz()
        print(f"✅ Hantek 1008C inicializado e calibrado em {init_dt:.2f}s | Sample Rate: {sr_hz:.0f} Hz ({ns_per_div/1000:.0f} µs/div)")

        data = scope.capture_burst(as_volts=True)
        print("\n📊 RESULTADO DA CAPTURA POR CANAL:")
        print("=" * 78)

        export_doc = {
            "device": "Hantek 1008C (USB 0783:5725)",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ns_per_div": ns_per_div,
            "sample_rate_hz": sr_hz,
            "zero_offsets": scope.zero_offsets,
            "channels": {},
        }

        for ch0 in active_0based:
            samples = [float(v) for v in data.get(ch0, [])]
            m = scope.compute_channel_metrics(samples, sr_hz)
            ch_num = ch0 + 1
            print(
                f"• [CH{ch_num} | Atenuação {atten_map[ch0]:g}x] {len(samples)} amostras | "
                f"Vmin={m['vmin']:+.3f}V | Vmax={m['vmax']:+.3f}V | Vmean={m['vmean']:+.3f}V | "
                f"Vpp={m['vpp']:.3f}V | Vrms={m['vrms']:.3f}V | Duty={m['duty_pct']:.1f}% | Freq={m['freq_hz']:.1f}Hz"
            )
            export_doc["channels"][f"CH{ch_num}"] = {
                "attenuation": atten_map[ch0],
                "metrics": m,
                "samples": samples,
            }

        ch1_list = [float(v) for v in data.get(active_0based[0], [])]
        ch2_list = [float(v) for v in data.get(active_0based[1], [])] if len(active_0based) > 1 else []
        m1 = scope.compute_channel_metrics(ch1_list, sr_hz)
        cap_id = persist_capture_to_sqlite(ch1_list, ch2_list, sr_hz, m1)
        if cap_id:
            print(f"\n💾 Captura persistida no banco SQLite cardiag.db (osc_captures ID={cap_id}).")

        if out_json:
            out_p = Path(out_json)
            with open(out_p, "w", encoding="utf-8") as f:
                json.dump(export_doc, f, ensure_ascii=False, indent=2)
            print(f"📁 Arquivo JSON exportado para: {out_p}")

        return 0
    finally:
        scope.close()


async def run_ws_bridge(
    ws_url: str,
    serial_id: str,
    token: Optional[str],
    channels_1based: List[int],
    ns_per_div: int,
    vscale: float,
    attenuations: List[float],
    fps: float = 8.0,
) -> int:
    import websockets

    active_0based = [max(0, min(7, c - 1)) for c in channels_1based]
    if len(active_0based) < 2:
        active_0based = sorted(list(set(active_0based + [0, 1])))[:2]

    atten_map = [1.0] * 8
    for idx, ch0 in enumerate(active_0based):
        if idx < len(attenuations):
            atten_map[ch0] = attenuations[idx]

    print(f"🔌 Inicializando Hantek 1008C (Canais {[c+1 for c in active_0based]})...")
    scope = Hantek1008C(
        ns_per_div=ns_per_div,
        vertical_scale_factor=vscale,
        active_channels=active_0based,
        probe_attenuation=atten_map,
    )
    scope.connect()
    try:
        scope.init(calibrate_all_scales=True)
        sr_hz = int(scope.get_effective_sample_rate_hz())
        print(f"✅ Hantek 1008C pronto ({sr_hz} Hz). Conectando ao servidor WebSocket: {ws_url}")

        sep = "&" if "?" in ws_url else "?"
        full_url = f"{ws_url}{sep}node_id={serial_id}"
        if token:
            full_url += f"&token={token}"

        async with websockets.connect(full_url) as ws:
            # Envia handshake caso o servidor solicite autenticação inicial
            await ws.send(
                json.dumps(
                    {
                        "type": "handshake",
                        "serial": serial_id,
                        "node_id": serial_id,
                        "device_type": "Osciloscopio",
                        "hw": "Hantek_1008C_8CH",
                        "fw": "v2.5.2",
                        "token": token or "",
                    }
                )
            )
            print("🟢 Streaming de formas de onda do Hantek 1008C ativo para o Dashboard AgentCarDiag! (Ctrl+C para parar)")
            interval = 1.0 / max(1.0, fps)
            frame_count = 0
            while True:
                t_start = time.time()
                data = scope.capture_burst(as_volts=True)
                ch1_s = [float(v) for v in data.get(active_0based[0], [])][:512]
                ch2_s = [float(v) for v in data.get(active_0based[1], [])][:512]
                m1 = scope.compute_channel_metrics(ch1_s, sr_hz)

                payload = {
                    "type": "adc_burst",
                    "serial": serial_id,
                    "device": "Hantek_1008C",
                    "sample_rate": sr_hz,
                    "ch1": ch1_s,
                    "ch2": ch2_s,
                    "vmin": m1["vmin"],
                    "vmax": m1["vmax"],
                    "vmean": m1["vmean"],
                    "vpp": m1["vpp"],
                    "vrms": m1["vrms"],
                    "duty_pct": m1["duty_pct"],
                    "freq_hz": m1["freq_hz"],
                }
                await ws.send(json.dumps(payload, separators=(",", ":")))
                frame_count += 1
                if frame_count % 10 == 0:
                    print(
                        f"[Frame #{frame_count:04d}] CH{active_0based[0]+1}: Vmin={m1['vmin']:+.2f}V "
                        f"Vmax={m1['vmax']:+.2f}V Vpp={m1['vpp']:.2f}V Freq={m1['freq_hz']:.1f}Hz"
                    )
                elapsed = time.time() - t_start
                if elapsed < interval:
                    await asyncio.sleep(interval - elapsed)
    finally:
        scope.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hantek 1008C Automotive Oscilloscope CLI & WebSocket Bridge")
    parser.add_argument("--capture", action="store_true", help="Executa captura Burst, exibe métricas e salva no banco")
    parser.add_argument("--ws", type=str, help="Inicia streaming em tempo real para o WebSocket (ex: ws://127.0.0.1:8000/ws/hardware)")
    parser.add_argument("--serial", type=str, default="virtual_car_node", help="ID do nó ou serial (default: virtual_car_node para loopback local)")
    parser.add_argument("--token", type=str, default="", help="Token do dispositivo se necessário")
    parser.add_argument("--ch", type=int, nargs="+", default=[1, 2], help="Canais ativos 1..8 (ex: --ch 1 2 3 4)")
    parser.add_argument("--ns-div", type=int, default=500_000, help="Base de tempo em ns/div (ex: 500000 = 500us/div, 1000000 = 1ms/div)")
    parser.add_argument("--vscale", type=float, default=1.0, choices=[0.02, 0.125, 1.0], help="Fator de escala vertical (1.0, 0.125, 0.02)")
    parser.add_argument("--atten", type=float, nargs="+", default=[1.0, 1.0], help="Fator de atenuação da ponta por canal (ex: --atten 20 1 para HT201)")
    parser.add_argument("--out", type=str, help="Exportar amostras e métricas para arquivo JSON")
    parser.add_argument("--full-cal", action="store_true", help="Calibrar zero offset em todas as 3 escalas verticais")
    args = parser.parse_args()

    if args.ws:
        return asyncio.run(
            run_ws_bridge(
                ws_url=args.ws,
                serial_id=args.serial,
                token=args.token or None,
                channels_1based=args.ch,
                ns_per_div=args.ns_div,
                vscale=args.vscale,
                attenuations=args.atten,
            )
        )

    return run_cli_capture(
        channels_1based=args.ch,
        ns_per_div=args.ns_div,
        vscale=args.vscale,
        attenuations=args.atten,
        out_json=args.out,
        calibrate_all=True,
    )


if __name__ == "__main__":
    sys.exit(main())
