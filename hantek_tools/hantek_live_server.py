#!/usr/bin/env python3
"""
hantek_live_server.py — Servidor Local de Streaming Ao Vivo do Osciloscópio Hantek 1008C (USB 0783:5725)
Projeto AgentCarDiag

Mantém a conexão USB com o Hantek 1008C aberta continuamente (após a calibração de 3 escalas)
e transmite pacotes de 2.000 amostras reais a ~10-15 quadros por segundo via HTTP CORS / JSON
na porta 8765 para alimentar diretamente a mini-tela gráfica inline do chat (<agent-embed>)!
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hantek1008_driver import Hantek1008C

LIVE_STATE: Dict[str, object] = {
    "connected": False,
    "frame_id": 0,
    "timestamp": 0.0,
    "sample_rate_hz": 400000.0,
    "ns_per_div": 500000,
    "ch1": [],
    "ch2": [],
    "metrics_ch1": {"vmin": 0.0, "vmax": 0.0, "vmean": 0.0, "vpp": 0.0, "vrms": 0.0, "duty_pct": 0.0, "freq_hz": 0.0},
    "metrics_ch2": {"vmin": 0.0, "vmax": 0.0, "vmean": 0.0, "vpp": 0.0, "vrms": 0.0, "duty_pct": 0.0, "freq_hz": 0.0},
    "error": "",
}
STATE_LOCK = threading.Lock()


def acquisition_loop(channels_1based: List[int], ns_per_div: int, vscale: float, attenuations: List[float]) -> None:
    active_0based = [max(0, min(7, c - 1)) for c in channels_1based]
    if len(active_0based) < 2:
        active_0based = sorted(list(set(active_0based + [0, 1])))[:2]

    atten_map = [1.0] * 8
    for idx, ch0 in enumerate(active_0based):
        if idx < len(attenuations):
            atten_map[ch0] = attenuations[idx]

    while True:
        scope = None
        try:
            if not Hantek1008C.is_connected():
                with STATE_LOCK:
                    LIVE_STATE["connected"] = False
                    LIVE_STATE["error"] = "Hantek 1008C desconectado do USB"
                time.sleep(1.5)
                continue

            scope = Hantek1008C(
                ns_per_div=ns_per_div,
                vertical_scale_factor=vscale,
                active_channels=active_0based,
                probe_attenuation=atten_map,
            )
            scope.connect()
            scope.init(calibrate_all_scales=True)
            sr_hz = scope.get_effective_sample_rate_hz()
            print(f"🟢 [HantekLiveServer] USB Inicializado ({sr_hz:.0f} Hz). Puxando dados ao vivo continuamente...")

            frame_id = 0
            while True:
                data = scope.capture_burst(as_volts=True)
                c1_idx = active_0based[0]
                c2_idx = active_0based[1]
                s1 = [float(v) for v in data.get(c1_idx, [])]
                s2 = [float(v) for v in data.get(c2_idx, [])]
                m1 = scope.compute_channel_metrics(s1, sr_hz)
                m2 = scope.compute_channel_metrics(s2, sr_hz)
                frame_id += 1

                with STATE_LOCK:
                    LIVE_STATE["connected"] = True
                    LIVE_STATE["frame_id"] = frame_id
                    LIVE_STATE["timestamp"] = time.time()
                    LIVE_STATE["sample_rate_hz"] = sr_hz
                    LIVE_STATE["ns_per_div"] = ns_per_div
                    LIVE_STATE["ch1"] = s1[:600]
                    LIVE_STATE["ch2"] = s2[:600]
                    LIVE_STATE["metrics_ch1"] = m1
                    LIVE_STATE["metrics_ch2"] = m2
                    LIVE_STATE["error"] = ""

                time.sleep(0.04)
        except Exception as e:
            with STATE_LOCK:
                LIVE_STATE["connected"] = False
                LIVE_STATE["error"] = str(e)
            if scope:
                try:
                    scope.close()
                except Exception:
                    pass
            time.sleep(1.5)


class LiveScopeHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/live"):
            with STATE_LOCK:
                payload = json.dumps(LIVE_STATE, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404)
            self.end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor Ao Vivo USB Hantek 1008C (Porta 8765)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ch", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--ns-div", type=int, default=500_000)
    parser.add_argument("--vscale", type=float, default=1.0)
    parser.add_argument("--atten", type=float, nargs="+", default=[1.0, 1.0])
    args = parser.parse_args()

    t = threading.Thread(
        target=acquisition_loop,
        args=(args.ch, args.ns_div, args.vscale, args.atten),
        daemon=True,
    )
    t.start()

    server = HTTPServer(("127.0.0.1", args.port), LiveScopeHandler)
    print(f"🌐 [HantekLiveServer] Escutando em http://127.0.0.1:{args.port}/live")
    server.serve_forever()


if __name__ == "__main__":
    main()
