#!/usr/bin/env python3
"""
vlinker_diag.py — Cliente e Bridge BLE 4.0+ para Vgate vLinker MC+ (C0:25:E8:5A:95:ED)
Projeto AgentCarDiag — Suporta CAN 11/29-bit (ISO 15765-4 / UDS ISO 14229),
KWP2000 (ISO 14230-4 5-Baud & Fast Init, inclusive Sessão Nativa VAG 10 89) e ISO 9141-2.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bleak import BleakClient

CONFIG_PATH = Path(__file__).resolve().parent / "vlinker_bluetooth_config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "ble_mac_address": "C0:25:E8:5A:95:ED",
        "gatt_service_uuid": "000018f0-0000-1000-8000-00805f9b34fb",
        "gatt_notify_rx_uuid": "00002af0-0000-1000-8000-00805f9b34fb",
        "gatt_write_tx_uuid": "00002af1-0000-1000-8000-00805f9b34fb",
    }


class VLinkerBLE:
    """
    Cliente assíncrono Bluetooth LE para o Vgate vLinker MC+ (vLinker MC-IOS).
    Implementa sincronismo estrito por prompt '>' e filtros de hardware CAN (ATCRA)
    para eliminar 100% os erros de BUFFER FULL em redes automotivas densas.
    """

    def __init__(self, config: Optional[dict] = None, protocol: str = "6"):
        self.cfg = config or load_config()
        self.address = self.cfg["ble_mac_address"]
        self.notify_uuid = self.cfg["gatt_notify_rx_uuid"]
        self.write_uuid = self.cfg["gatt_write_tx_uuid"]
        self.protocol = protocol
        self.client: Optional[BleakClient] = None
        self._rx_buf = bytearray()
        self._done_evt = asyncio.Event()
        self.current_tx_header = "7DF"

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        self._rx_buf.extend(data)
        if b">" in self._rx_buf:
            self._done_evt.set()

    async def __aenter__(self) -> "VLinkerBLE":
        self.client = BleakClient(self.address, timeout=12.0)
        await self.client.__aenter__()
        await self.client.start_notify(self.notify_uuid, self._on_notify)
        await self.cmd("ATZ", timeout=3.0)
        await asyncio.sleep(0.2)
        await self.cmd("ATE0")
        await self.cmd("ATL0")
        await self.cmd("ATS1")
        await self.cmd("ATH1")
        await self.cmd("ATAL")
        await self.cmd(f"ATSP{self.protocol}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client:
            try:
                await self.restore_broadcast()
            except Exception:
                pass
            await self.client.__aexit__(exc_type, exc, tb)

    async def cmd(self, command: str, timeout: float = 3.5) -> str:
        """Envia um comando AT ou Hex e aguarda rigorosamente o prompt '>'."""
        if not self.client:
            raise RuntimeError("Cliente BLE não inicializado.")
        self._rx_buf.clear()
        self._done_evt.clear()
        await self.client.write_gatt_char(
            self.write_uuid, (command.strip() + "\r").encode("ascii"), response=False
        )
        try:
            await asyncio.wait_for(self._done_evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return (
            self._rx_buf.decode("ascii", errors="ignore")
            .replace("\r", "\n")
            .replace(">", "")
            .strip()
        )

    async def set_can_target(self, tx_id: str, rx_id: Optional[str] = None) -> None:
        """
        Configura endereçamento físico CAN, filtro de hardware ATCRA e Flow Control ISO-TP.
        Regra de Ouro Anti-Saturação (evita BUFFER FULL em redes com alto tráfego como Sprinter W910).
        """
        tx_clean = tx_id.replace("0x", "").strip().upper()
        if not rx_id:
            if len(tx_clean) == 3 and tx_clean.startswith("7E") and tx_clean != "7DF":
                rx_clean = f"{int(tx_clean, 16) + 8:03X}"
            else:
                rx_clean = ""
        else:
            rx_clean = rx_id.replace("0x", "").strip().upper()

        await self.cmd(f"ATSH {tx_clean}")
        if rx_clean:
            await self.cmd(f"ATCRA {rx_clean}")
            await self.cmd(f"ATFCSH {tx_clean}")
            await self.cmd("ATFCSD 300000")
            await self.cmd("ATFCSM 1")
        else:
            await self.cmd("ATAR")
        self.current_tx_header = tx_clean

    async def restore_broadcast(self) -> None:
        """Limpa filtros físicos CAN e retorna ao endereço funcional OBD-II 7DF."""
        await self.cmd("ATAR")
        await self.cmd("ATSH 7DF")
        self.current_tx_header = "7DF"

    async def ensure_kwp_init(self, retries: int = 3) -> Tuple[bool, str]:
        """
        Garante inicialização estável em protocolos K-Line (ISO 14230-4 KWP 5-Baud/Fast Init e ISO 9141-2).
        Evita falhas de BUS INIT: ...ERROR após timeout P3 (~5s de inatividade).
        """
        await self.cmd("ATSP0")
        for attempt in range(1, retries + 1):
            resp = await self.cmd("0100", timeout=15.0)
            if "41 00" in resp.upper() or "4100" in resp.replace(" ", "").upper():
                dp = await self.cmd("ATDP")
                return True, f"K-Line / OBD inicializado na tentativa {attempt} ({dp})"
            await asyncio.sleep(1.0)
        return False, "Falha ao inicializar barramento K-Line após múltiplas tentativas."


def parse_kwp_or_can_pid_bytes(raw_resp: str, expected_reply_hex: str) -> List[int]:
    """
    Extrai os bytes úteis de uma resposta OBD/UDS/KWP tanto em CAN (ATH1: '7E8 06 41 0C 1A F8')
    quanto em K-Line KWP2000/ISO9141 (ATH1: '84 F1 10 41 0C 0C 28 E3', removendo o checksum KWP final).
    """
    exp_tokens = [
        expected_reply_hex[i : i + 2].upper()
        for i in range(0, len(expected_reply_hex.replace(" ", "")), 2)
    ]
    for line in raw_resp.splitlines():
        s = line.strip().upper()
        if not s or any(err in s for err in ("NO DATA", "ERROR", "UNABLE", "STOPPED", "?", "SEARCHING", "BUS INIT")):
            continue
        parts = s.split()
        # Detecta cabeçalho K-Line (8X F1 10 ... ou 48 6B 10 ...) onde o último byte é checksum
        is_kline_hdr = len(parts) >= 5 and (
            (parts[0].startswith("8") and parts[1] == "F1")
            or (parts[0] == "48" and parts[1] == "6B")
        )
        for idx in range(len(parts) - len(exp_tokens) + 1):
            if parts[idx : idx + len(exp_tokens)] == exp_tokens:
                data_tokens = parts[idx + len(exp_tokens) : -1] if is_kline_hdr else parts[idx + len(exp_tokens) :]
                out: List[int] = []
                for tok in data_tokens:
                    if re.match(r"^[0-9A-F]{2}$", tok):
                        out.append(int(tok, 16))
                return out
    return []


async def run_quick_handshake(vl: VLinkerBLE) -> None:
    """
    Handshake cirúrgico de 3 comandos (Regra do Prompt Padrão Universal):
    1. ATRV (Tensão da bateria)
    2. 0902 / 22F190 (VIN)
    3. 03 (DTCs confirmados do motor)
    """
    atrv = await vl.cmd("ATRV")
    await vl.set_can_target("7E0", "7E8")
    r_vin = await vl.cmd("0902", timeout=3.5)
    if "NO DATA" in r_vin.upper() or "ERROR" in r_vin.upper() or "7F" in r_vin.upper():
        r_vin = await vl.cmd("22F190", timeout=3.5)
    r_dtc = await vl.cmd("03", timeout=3.5)
    await vl.restore_broadcast()

    print(f"🔋 Tensão OBD-II (ATRV): {atrv}")
    print(f"🆔 Resposta VIN        : {r_vin}")
    print(f"🚨 DTCs Motor (Modo 03): {r_dtc}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente BLE Vgate vLinker MC+ — AgentCarDiag")
    parser.add_argument("--proto", default="6", help="Protocolo ATSP (6=CAN 11b 500k, 7=CAN 29b 500k, 0=Auto, 4=KWP 5baud, 5=KWP Fast)")
    parser.add_argument("--tx", default="", help="Header TX físico opcional (ex: 7E0, 7E1, 713, 645)")
    parser.add_argument("--rx", default="", help="Filtro RX físico opcional (ex: 7E8, 7E9, 77D, 5C5)")
    parser.add_argument("--handshake", action="store_true", help="Executa o Handshake Cirúrgico Leve (ATRV, VIN, Modo 03)")
    parser.add_argument("cmds", nargs="*", help="Comandos AT/OBD/UDS a enviar (ex: ATRV 010C 0105 22F190)")
    args = parser.parse_args()

    async with VLinkerBLE(protocol=args.proto) as vl:
        if args.handshake:
            await run_quick_handshake(vl)
            return

        if args.tx:
            await vl.set_can_target(args.tx, args.rx or None)

        commands = args.cmds or ["ATRV", "010C", "010D", "0105", "010B", "0123", "0178"]
        for c in commands:
            res = await vl.cmd(c)
            print(f"[{c}] => {res}")


if __name__ == "__main__":
    asyncio.run(main())
