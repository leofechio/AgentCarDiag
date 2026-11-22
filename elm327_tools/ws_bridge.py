#!/usr/bin/env python3
"""
Ponte WebSocket (Bridge): Vgate vLinker MC+ (Bluetooth) <---> Servidor AgentCarDiag (/ws/esp32)
Permite usar o vLinker MC+ via Bluetooth do notebook exatamente como se fosse o hardware
ESP32-S3 oficial (`s2001`) diretamente no Painel Web do AgentCarDiag!
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elm327_core import ELM327Connection


async def run_bridge(bt_target: str, server_ws_url: str, serial_id: str = "s2001"):
    elm = ELM327Connection(target=bt_target)
    ok, msg = elm.connect()
    if not ok:
        print(f"❌ Erro ao conectar no vLinker MC+: {msg}")
        sys.exit(1)

    print(f"✅ vLinker MC+ conectado: {msg}")
    init_info = elm.initialize_elm("0")
    print(f"🔧 Inicialização ELM/STN: ATI={init_info.get('ATI')} | Tensão={init_info.get('ATRV')}")

    full_url = f"{server_ws_url.rstrip('/')}?type=scanner&serial={serial_id}"
    print(f"🌐 Conectando ao servidor AgentCarDiag: {full_url}")

    async with websockets.connect(full_url) as ws:
        print("🟢 Ponte ativa! O painel Web do AgentCarDiag já enxerga o vLinker MC+ como online.")
        # Envia pacote inicial de status
        await ws.send(json.dumps({
            "type": "status",
            "serial": serial_id,
            "proto": "can",
            "pin": 6,
            "module": "vLinker_MC_Plus",
            "voltage": init_info.get("ATRV", "12.6V"),
        }))

        async for message in ws:
            try:
                data = json.loads(message)
            except Exception:
                continue

            cmd = data.get("cmd", "")
            if cmd == "ping":
                await ws.send(json.dumps({"type": "pong", "serial": serial_id, "ts": time.time()}))
                continue

            # Comandos OBD / UDS vindos do painel web
            raw_hex = data.get("hex") or data.get("payload") or data.get("obd_cmd")
            header = data.get("header") or data.get("can_id") or "7DF"
            if raw_hex:
                elm.set_header(str(header))
                resp = elm.send_raw(str(raw_hex), timeout=2.5)
                await ws.send(json.dumps({
                    "type": "obd_response",
                    "serial": serial_id,
                    "cmd": raw_hex,
                    "header": header,
                    "raw": resp,
                }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bridge Bluetooth vLinker MC+ -> AgentCarDiag Web")
    parser.add_argument("--target", type=str, required=True, help="MAC Bluetooth do vLinker MC+ ou /dev/rfcomm0")
    parser.add_argument("--ws", type=str, default="ws://localhost:8000/ws/esp32", help="URL WebSocket do servidor")
    parser.add_argument("--serial", type=str, default="s2001", help="Serial virtual do scanner no painel")
    args = parser.parse_args()
    asyncio.run(run_bridge(args.target, args.ws, args.serial))
