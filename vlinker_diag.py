#!/usr/bin/env python3
"""
vlinker_diag.py — Cliente e Bridge BLE 4.0+ para Vgate vLinker MC+ (C0:25:E8:5A:95:ED)
Projeto AgentCarDiag — Arquitetura Revisada Pericial:

1. Inicialização independente para:
   - ISO 9141-2 (5-Baud Init, ATSP3, Header 68 6A F1)
   - ISO 14230-4 KWP2000 5-Baud Init (ATSP4, Header C2 33 F1 / 81 10 F1)
   - ISO 14230-4 KWP2000 Fast Init (ATSP5, Header C1 33 F1 / 81 10 F1 + 81 StartCommunication)
2. Handshake cirúrgico protocolo-consciente (não força ATSH 7E0/ATCRA 7E8 de 11-bit CAN quando estiver em K-Line).
3. Identificação automática e confirmação determinística do protocolo ativo (ATDP, ATDPN, ATKW).
4. Testes independentes de barramento CAN (11-bit/29-bit) vs K-Line (Pino 7 OBD-II).
5. Registro pericial de evidências (Evidence Record: timestamp, comando enviado, resposta bruta,
   protocolo confirmado, pino físico, latência e veredito).
6. Separação explícita entre K-Line padrão no Pino 7 (OBD-II Motor/Câmbio) e K-Line multiplexada
   em outros pinos (Pinos 1, 3, 8, 9, 11, 12, 13 — ABS/Airbag/Imobilizador/Chassi legados que
   exigem cabo comutador ou multiplexador físico externo, pois o transceiver K-Line do Vgate
   vLinker MC+ opera exclusivamente no Pino 7).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from bleak import BleakClient
except ImportError:
    BleakClient = None  # type: ignore

CONFIG_PATH = Path(__file__).resolve().parent / "vlinker_bluetooth_config.json"
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence_logs"

# Mapeamento oficial de códigos de protocolo ELM327 / STN (ATDPN)
PROTOCOL_MAP: Dict[str, Dict[str, str]] = {
    "1": {"name": "SAE J1850 PWM (41.6 kbaud)", "family": "J1850", "pins": "Pinos 2/10"},
    "2": {"name": "SAE J1850 VPW (10.4 kbaud)", "family": "J1850", "pins": "Pino 2"},
    "3": {"name": "ISO 9141-2 (5-Baud Init, 10.4 kbaud)", "family": "KLINE", "pins": "Pino 7 (K) + Pino 15 (L opcional)"},
    "4": {"name": "ISO 14230-4 KWP2000 (5-Baud Init, 10.4 kbaud)", "family": "KLINE", "pins": "Pino 7 (K) + Pino 15 (L opcional)"},
    "5": {"name": "ISO 14230-4 KWP2000 (Fast Init, 10.4 kbaud)", "family": "KLINE", "pins": "Pino 7 (K) + Pino 15 (L opcional)"},
    "6": {"name": "ISO 15765-4 CAN (11-bit ID, 500 kbaud)", "family": "CAN_11B", "pins": "Pinos 6 (CAN-H) / 14 (CAN-L)"},
    "7": {"name": "ISO 15765-4 CAN (29-bit ID, 500 kbaud)", "family": "CAN_29B", "pins": "Pinos 6 (CAN-H) / 14 (CAN-L)"},
    "8": {"name": "ISO 15765-4 CAN (11-bit ID, 250 kbaud)", "family": "CAN_11B", "pins": "Pinos 6 (CAN-H) / 14 (CAN-L)"},
    "9": {"name": "ISO 15765-4 CAN (29-bit ID, 250 kbaud)", "family": "CAN_29B", "pins": "Pinos 6 (CAN-H) / 14 (CAN-L)"},
    "A": {"name": "SAE J1939 CAN (29-bit ID, 250 kbaud)", "family": "CAN_29B", "pins": "Pinos 6/14"},
}

# Catálogo de topologia física K-Line: Pino 7 (Nativo no Vgate) vs Pinos Multiplexados (Fora do Pino 7)
KLINE_PIN_TOPOLOGY: Dict[str, Dict[str, Any]] = {
    "vag_b6_kline": {
        "vehicle_examples": "Audi A4/S4 B6 (2001-2005), VW Golf MK4 / Passat B5 (1998-2005)",
        "pin_7_modules": [
            {"name": "01 - Motor (ECM Bosch ME7.x / EDC15)", "target_addr": "10", "hdr_fast": "81 10 F1", "hdr_func": "C2 33 F1"},
            {"name": "02 - Transmissão Automática (TCM)", "target_addr": "18", "hdr_fast": "81 18 F1", "hdr_func": "C2 33 F1"},
            {"name": "03 - Freios ABS / ESP Bosch 5.7", "target_addr": "28", "hdr_fast": "81 28 F1", "hdr_func": "C2 33 F1"},
            {"name": "15 - Airbag / SRS", "target_addr": "58", "hdr_fast": "81 58 F1", "hdr_func": "C2 33 F1"},
            {"name": "17 - Painel de Instrumentos (Kombi / Immo)", "target_addr": "60", "hdr_fast": "81 60 F1", "hdr_func": "C2 33 F1"},
        ],
        "multiplexed_non_pin7_modules": [
            {
                "name": "Módulos Secundários K2-Line (Xenon Range, Rádio/Navegação, Conforto em plataformas Dual-K VAG)",
                "obd_pin": "Pino 15 (L-Line / K2-Line)",
                "vgate_native_support": False,
                "hardware_requirement": "O Vgate vLinker MC+ usa o Pino 15 apenas para pulso de inicialização L-Line, não como transceiver K2 bidirecional independente. Exige VCDS K+CAN ou ponte Pino 15->Pino 7.",
            }
        ],
    },
    "bmw_e46_kline": {
        "vehicle_examples": "BMW E46 (320i/320d/330i 1998-2006), BMW E39, E38, E53 X5",
        "pin_7_modules": [
            {"name": "DME / DDE (Injeção Motor Bosch DDE4/MS42/MS43)", "target_addr": "12", "hdr_fast": "81 12 F1", "hdr_func": "C2 33 F1"},
            {"name": "EGS (Transmissão Automática)", "target_addr": "18", "hdr_fast": "81 18 F1", "hdr_func": "C2 33 F1"},
        ],
        "multiplexed_non_pin7_modules": [
            {
                "name": "DSC/ABS (56), Airbag MRS (C0), Painel IKE (80), Carroceria ZKE/GM5 (00), Imobilizador EWS (44)",
                "obd_pin": "Pino 8 (K-Bus / I-Bus / D-Bus Carroceria BMW)",
                "vgate_native_support": False,
                "hardware_requirement": "No BMW E46/E39/E53 o Pino 7 fala APENAS com Motor (DME/DDE) e Câmbio (EGS). Todos os outros módulos estão na K-Line do Pino 8. Para acessá-los com Vgate/ELM327 é obrigatório usar adaptador OBD com ponte Pino 7+8 (cabo K+DCAN com chave 7-8).",
            }
        ],
    },
    "fiat_alfa_psa_legacy_kline": {
        "vehicle_examples": "Fiat Ducato / Doblo / Palio / Stilo, Alfa Romeo 147/156, Peugeot 206 / Citroën C3 (1999-2007)",
        "pin_7_modules": [
            {"name": "ECM Injeção Motor (Bosch EDC15/EDC16/ME7/Marelli IAW)", "target_addr": "10", "hdr_fast": "81 10 F1", "hdr_func": "C1 33 F1"},
        ],
        "multiplexed_non_pin7_modules": [
            {
                "name": "ABS / ESP Bosch",
                "obd_pin": "Pino 1 (K-Line ABS Fiat/Alfa)",
                "vgate_native_support": False,
                "hardware_requirement": "No Vgate vLinker MC+ o Pino 1 é um transceiver SW-CAN (Single-Wire CAN 33.3kbps da GM), NÃO uma K-Line ISO 9141. Exige cabo adaptador colorido MultiECUScan (Verde - Pino 1 -> Pino 7).",
            },
            {
                "name": "Airbag / SRS TRW/Siemens",
                "obd_pin": "Pino 3 (K-Line Airbag Fiat/Alfa)",
                "vgate_native_support": False,
                "hardware_requirement": "No Vgate vLinker MC+ os Pinos 3/11 são um transceiver MS-CAN diferencial (Ford), NÃO uma K-Line. Exige cabo adaptador colorido MultiECUScan (Vermelho - Pino 3 -> Pino 7).",
            },
            {
                "name": "Direção Elétrica / Xenon / Clima",
                "obd_pin": "Pinos 9, 12 ou 13 (K-Line Chassi/Direção)",
                "vgate_native_support": False,
                "hardware_requirement": "Pinos 9, 12 e 13 não possuem transceiver no Vgate vLinker MC+. Exige cabo adaptador MultiECUScan (Roxo/Amarelo) roteando para o Pino 7.",
            },
        ],
    },
    "mercedes_sprinter_w901_w906_kline": {
        "vehicle_examples": "Mercedes Sprinter CDI (2000-2013), Classe C W203 / Classe E W211 legados",
        "pin_7_modules": [
            {"name": "CDI / ECM Motor (OBD-II / KWP2000 Pino 7)", "target_addr": "10", "hdr_fast": "81 10 F1", "hdr_func": "C1 33 F1"},
        ],
        "multiplexed_non_pin7_modules": [
            {
                "name": "ESP/ABS (Pino 9), Airbag/SRS (Pino 13), Imobilizador WSP/EWM (Pino 11), Ar/Aquecedor (Pino 12)",
                "obd_pin": "Pinos 8, 9, 11, 12, 13 (K-Lines Multiplexadas Mercedes)",
                "vgate_native_support": False,
                "hardware_requirement": "O Vgate vLinker MC+ lê apenas o Pino 7 em K-Line. Para os pinos 8/9/11/12/13 é necessário multiplexador (ex: Launch DBScar VII + SmartBox ou cabo breakout comutando o pino desejado para o Pino 7).",
            }
        ],
    },
}


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


def classify_response_result(raw_resp: str) -> str:
    """Classifica objetivamente o resultado de um comando para o registro pericial de evidências."""
    u = raw_resp.strip().upper()
    if not u:
        return "TIMEOUT_EMPTY"
    if "BUFFER FULL" in u:
        return "ERROR_BUFFER_FULL"
    if "BUS INIT" in u and "ERROR" in u:
        return "ERROR_BUS_INIT"
    if "UNABLE TO CONNECT" in u:
        return "ERROR_UNABLE_TO_CONNECT"
    if "CAN ERROR" in u:
        return "ERROR_CAN_BUS"
    if "NO DATA" in u:
        return "NO_DATA"
    if "?" in u:
        return "INVALID_COMMAND"
    if re.search(r"\b7F\s+[0-9A-F]{2}\s+[0-9A-F]{2}\b", u) or re.search(r"7F[0-9A-F]{4}", u.replace(" ", "")):
        return "NEGATIVE_RESPONSE_NRC"
    if "OK" in u or re.search(r"[0-9A-F]{2}", u):
        return "POSITIVE_RESPONSE"
    return "INFO_RESPONSE"


class VLinkerBLE:
    """
    Cliente assíncrono Bluetooth LE para o Vgate vLinker MC+ (vLinker MC-IOS).
    Inclui inicialização independente de CAN e K-Line (ISO 9141-2, KWP 5-Baud, KWP Fast Init),
    detecção/confirmação automática de protocolo e registro estruturado de evidências periciais.
    """

    def __init__(self, config: Optional[dict] = None, protocol: str = "0"):
        self.cfg = config or load_config()
        self.address = self.cfg["ble_mac_address"]
        self.notify_uuid = self.cfg["gatt_notify_rx_uuid"]
        self.write_uuid = self.cfg["gatt_write_tx_uuid"]
        self.protocol = protocol.upper()
        self.client: Optional[BleakClient] = None
        self._rx_buf = bytearray()
        self._done_evt = asyncio.Event()

        # Estado de protocolo confirmado
        self.active_protocol_code: str = self.protocol
        self.active_protocol_name: str = "UNCONFIRMED"
        self.active_protocol_family: str = "UNKNOWN"  # 'CAN_11B', 'CAN_29B', 'KLINE', 'J1850'
        self.active_physical_pins: str = "Pino 16 (+12V) / Pinos 4-5 (GND)"
        self.current_tx_header: str = ""

        # Registro Pericial de Evidências (Audit Trail)
        self.evidence_log: List[Dict[str, Any]] = []

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        self._rx_buf.extend(data)
        if b">" in self._rx_buf:
            self._done_evt.set()

    async def __aenter__(self) -> "VLinkerBLE":
        self.client = BleakClient(self.address, timeout=12.0)
        await self.client.__aenter__()
        await self.client.start_notify(self.notify_uuid, self._on_notify)
        await self.base_adapter_reset()
        if self.protocol != "0":
            await self.cmd(f"ATSP{self.protocol}", context="Configuração inicial de protocolo")
            self._update_protocol_state_from_code(self.protocol)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client:
            try:
                await self.restore_default_state()
            except Exception:
                pass
            await self.client.__aexit__(exc_type, exc, tb)

    async def base_adapter_reset(self) -> None:
        """Executa o reset base do Vgate sem forçar cabeçalhos CAN ou K-Line."""
        await self.cmd("ATZ", timeout=3.0, context="Reset de hardware ATZ")
        await asyncio.sleep(0.2)
        await self.cmd("ATE0", context="Desativar Eco")
        await self.cmd("ATL0", context="Desativar Linefeeds")
        await self.cmd("ATS1", context="Ativar Espaços entre Bytes Hex")
        await self.cmd("ATH1", context="Ativar Exibição de Cabeçalhos e Checksum")
        await self.cmd("ATAL", context="Permitir Mensagens Longas (>7 bytes)")

    def _update_protocol_state_from_code(self, dpn_raw: str, dp_text: str = "") -> None:
        code = dpn_raw.strip().upper().replace("A", "", 1) if dpn_raw.strip().upper().startswith("A") and len(dpn_raw.strip()) == 2 else dpn_raw.strip().upper()
        meta = PROTOCOL_MAP.get(code)
        if meta:
            self.active_protocol_code = code
            self.active_protocol_name = dp_text.strip() or meta["name"]
            self.active_protocol_family = meta["family"]
            self.active_physical_pins = meta["pins"]
        else:
            self.active_protocol_code = code or "0"
            self.active_protocol_name = dp_text.strip() or "AUTO / DESCONHECIDO"

    @property
    def is_kline(self) -> bool:
        return self.active_protocol_family == "KLINE" or self.active_protocol_code in ("3", "4", "5")

    @property
    def is_can(self) -> bool:
        return self.active_protocol_family in ("CAN_11B", "CAN_29B") or self.active_protocol_code in ("6", "7", "8", "9", "A")

    async def cmd(self, command: str, timeout: float = 3.5, context: str = "") -> str:
        """
        Envia um comando AT ou Hex, aguarda rigorosamente o prompt '>' e grava um
        Registro Pericial de Evidência (comando enviado, resposta, protocolo, pino e resultado).
        """
        if not self.client:
            raise RuntimeError("Cliente BLE não inicializado.")
        self._rx_buf.clear()
        self._done_evt.clear()
        t0 = time.perf_counter()
        await self.client.write_gatt_char(
            self.write_uuid, (command.strip() + "\r").encode("ascii"), response=False
        )
        timed_out = False
        try:
            await asyncio.wait_for(self._done_evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        resp = (
            self._rx_buf.decode("ascii", errors="ignore")
            .replace("\r", "\n")
            .replace(">", "")
            .strip()
        )
        verdict = "TIMEOUT" if (timed_out and not resp) else classify_response_result(resp)

        self.evidence_log.append(
            {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "command_sent": command.strip(),
                "response_received": resp,
                "protocol_code": self.active_protocol_code,
                "protocol_identified": self.active_protocol_name,
                "protocol_family": self.active_protocol_family,
                "physical_pins": self.active_physical_pins,
                "tx_header": self.current_tx_header,
                "latency_ms": elapsed_ms,
                "result": verdict,
                "context": context,
            }
        )
        return resp

    def save_evidence_report(self, filename_prefix: str = "vgate_evidence") -> Path:
        """Salva todos os registros de evidência da sessão em JSON estruturado para laudo pericial."""
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = EVIDENCE_DIR / f"{filename_prefix}_{ts}.json"
        payload = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "adapter": "Vgate vLinker MC+ BLE",
            "ble_mac": self.address,
            "confirmed_protocol_code": self.active_protocol_code,
            "confirmed_protocol_name": self.active_protocol_name,
            "confirmed_protocol_family": self.active_protocol_family,
            "confirmed_physical_pins": self.active_physical_pins,
            "total_commands": len(self.evidence_log),
            "evidence_records": self.evidence_log,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return out_path

    # ==========================================================================
    # 1. INICIALIZAÇÃO INDEPENDENTE PARA ISO 9141-2, KWP 5-BAUD E KWP FAST INIT
    # ==========================================================================

    async def init_iso9141_5baud(
        self, target_addr: str = "33", tester_addr: str = "F1", pin: int = 7
    ) -> Dict[str, Any]:
        """
        Inicialização independente para ISO 9141-2 (5-Baud Init, 10.4 kbaud — ATSP3).
        - Padrão funcional OBD-II: Header '68 6A F1'
        - Endereçamento físico opcional: Header '48 <target_addr> <tester_addr>'
        - Verifica Keywords via ATKW e mantém barramento vivo com ATIB10 / ATSW96.
        """
        pin_check = self.verify_kline_pin_capability(pin)
        if not pin_check["supported_natively"]:
            return pin_check

        await self.cmd("ATAR", context="Limpar filtros CAN antes de ISO 9141-2")
        await self.cmd("ATSP3", context="Selecionar ISO 9141-2 (5-Baud Init, 10.4 kbaud)")
        await self.cmd("ATIB10", context="Configurar baudrate ISO 10.4 kbaud")
        await self.cmd("ATSW96", context="Configurar wakeup keep-alive ISO 9141 (3.0s)")
        await self.cmd("ATST64", context="Configurar timeout P2 400ms para K-Line")

        hdr = "68 6A F1" if target_addr.upper() == "33" else f"48 {target_addr.upper()} {tester_addr.upper()}"
        await self.cmd(f"ATSH {hdr}", context=f"Header ISO 9141-2 ({hdr})")
        self.current_tx_header = hdr
        self._update_protocol_state_from_code("3", "ISO 9141-2 (5-Baud Init)")

        # Dispara 5-Baud Init enviando 0100 (timeout longo pois 5-baud leva ~3.5s)
        r_init = await self.cmd("01 00", timeout=12.0, context="Disparo 5-Baud Init ISO 9141-2 (01 00)")
        kw = await self.cmd("ATKW", context="Leitura das Key Words ISO 9141-2")
        dp = await self.cmd("ATDP", context="Confirmação do protocolo ISO 9141-2")
        dpn = await self.cmd("ATDPN", context="Código numérico do protocolo")
        self._update_protocol_state_from_code(dpn, dp)

        ok = "41 00" in r_init.upper() or "4100" in r_init.replace(" ", "").upper()
        return {
            "protocol": "ISO 9141-2 (5-Baud Init)",
            "atsp": "3",
            "pin": pin,
            "header": hdr,
            "success": ok,
            "keywords": kw,
            "atdp": dp,
            "atdpn": dpn,
            "init_response": r_init,
        }

    async def init_kwp2000_5baud(
        self, target_addr: str = "33", tester_addr: str = "F1", pin: int = 7
    ) -> Dict[str, Any]:
        """
        Inicialização independente para ISO 14230-4 KWP2000 5-Baud Init (10.4 kbaud — ATSP4).
        - Endereçamento funcional OBD-II: Header 'C2 33 F1'
        - Endereçamento físico (ex: VAG ECM 0x10, ABS 0x28): Header '81 <target_addr> <tester_addr>'
        """
        pin_check = self.verify_kline_pin_capability(pin)
        if not pin_check["supported_natively"]:
            return pin_check

        await self.cmd("ATAR", context="Limpar filtros CAN antes de KWP2000 5-Baud")
        await self.cmd("ATSP4", context="Selecionar ISO 14230-4 KWP (5-Baud Init, 10.4 kbaud)")
        await self.cmd("ATIB10", context="Configurar baudrate KWP 10.4 kbaud")
        await self.cmd("ATSW96", context="Configurar TesterPresent automático KWP (3.0s)")
        await self.cmd("ATST64", context="Configurar timeout P2 400ms para KWP")

        hdr = "C2 33 F1" if target_addr.upper() == "33" else f"81 {target_addr.upper()} {tester_addr.upper()}"
        await self.cmd(f"ATSH {hdr}", context=f"Header KWP2000 5-Baud ({hdr})")
        self.current_tx_header = hdr
        self._update_protocol_state_from_code("4", "ISO 14230-4 KWP (5-Baud Init)")

        r_init = await self.cmd("01 00", timeout=12.0, context="Disparo 5-Baud Init KWP2000 (01 00)")
        ok = "41 00" in r_init.upper() or "4100" in r_init.replace(" ", "").upper()

        # Caso seja um módulo físico (ex: ABS 0x28 ou ECM em sessão nativa) que não responde a 01 00, tenta StartDiagnosticSession (10 89 / 1A 9B)
        if not ok and target_addr.upper() != "33":
            r_sess = await self.cmd("10 89", timeout=8.0, context="Tentativa de Sessão Nativa KWP2000 (10 89)")
            if "50 89" in r_sess.upper() or "5089" in r_sess.replace(" ", "").upper():
                ok = True
                r_init = r_sess

        kw = await self.cmd("ATKW", context="Leitura das Key Words KWP2000 5-Baud")
        dp = await self.cmd("ATDP", context="Confirmação do protocolo KWP2000 5-Baud")
        dpn = await self.cmd("ATDPN", context="Código numérico do protocolo")
        self._update_protocol_state_from_code(dpn, dp)

        return {
            "protocol": "ISO 14230-4 KWP2000 (5-Baud Init)",
            "atsp": "4",
            "pin": pin,
            "header": hdr,
            "success": ok,
            "keywords": kw,
            "atdp": dp,
            "atdpn": dpn,
            "init_response": r_init,
        }

    async def init_kwp2000_fast(
        self, target_addr: str = "10", tester_addr: str = "F1", functional: bool = False, pin: int = 7
    ) -> Dict[str, Any]:
        """
        Inicialização independente para ISO 14230-4 KWP2000 Fast Init (10.4 kbaud — ATSP5).
        - Pulso wakeup T_iniL = 25ms Low / T_WUP = 50ms seguido de StartCommunication (0x81 -> 0xC1).
        - Físico direto (ex: Motor 0x10, ABS 0x28, Airbag 0x58, BMW DME 0x12): Header '81 <target_addr> <tester_addr>'
        - Funcional OBD-II: Header 'C1 33 F1'
        """
        pin_check = self.verify_kline_pin_capability(pin)
        if not pin_check["supported_natively"]:
            return pin_check

        await self.cmd("ATAR", context="Limpar filtros CAN antes de KWP2000 Fast Init")
        await self.cmd("ATSP5", context="Selecionar ISO 14230-4 KWP (Fast Init, 10.4 kbaud)")
        await self.cmd("ATIB10", context="Configurar baudrate KWP 10.4 kbaud")
        await self.cmd("ATSW96", context="Configurar TesterPresent keep-alive KWP (3.0s)")
        await self.cmd("ATST64", context="Configurar timeout P2 400ms")

        hdr = "C1 33 F1" if functional else f"81 {target_addr.upper()} {tester_addr.upper()}"
        await self.cmd(f"ATSH {hdr}", context=f"Header KWP2000 Fast Init ({hdr})")
        self.current_tx_header = hdr
        self._update_protocol_state_from_code("5", "ISO 14230-4 KWP (Fast Init)")

        # 1. Tenta pulso explícito ATFI + 01 00 (ou 81 StartCommunication / 3E TesterPresent)
        r_fi = await self.cmd("ATFI", timeout=5.0, context="Executar Fast Init físico (ATFI)")
        r_init = r_fi
        ok = "BUS INIT: OK" in r_fi.upper()

        # Confirma com serviço real (01 00 se funcional/motor, ou 3E / 10 89 se módulo físico dedicado)
        if functional or target_addr.upper() in ("10", "12", "33"):
            r_probe = await self.cmd("01 00", timeout=6.0, context="Sonda OBD 01 00 pós-Fast Init")
            if "41 00" in r_probe.upper() or "4100" in r_probe.replace(" ", "").upper():
                ok = True
                r_init = r_probe

        if not ok:
            # Tenta sessão diagnóstica nativa KWP2000 (10 89 VAG ou 1A 80 / 3E)
            r_sess = await self.cmd("10 89", timeout=6.0, context="Sonda Sessão Nativa KWP (10 89) via Fast Init")
            if "50 89" in r_sess.upper() or "5089" in r_sess.replace(" ", "").upper() or "7F 10" in r_sess.upper():
                ok = True
                r_init = r_sess

        kw = await self.cmd("ATKW", context="Leitura das Key Words KWP2000 Fast Init")
        dp = await self.cmd("ATDP", context="Confirmação do protocolo KWP2000 Fast Init")
        dpn = await self.cmd("ATDPN", context="Código numérico do protocolo")
        self._update_protocol_state_from_code(dpn, dp)

        return {
            "protocol": "ISO 14230-4 KWP2000 (Fast Init)",
            "atsp": "5",
            "pin": pin,
            "header": hdr,
            "success": ok,
            "keywords": kw,
            "atdp": dp,
            "atdpn": dpn,
            "init_response": r_init,
        }

    # ==========================================================================
    # 6. SEPARAÇÃO DE K-LINE NO PINO 7 vs K-LINE MULTIPLEXADA EM OUTROS PINOS
    # ==========================================================================

    @staticmethod
    def verify_kline_pin_capability(pin: int = 7) -> Dict[str, Any]:
        """
        Separa explicitamente a K-Line padrão no Pino 7 (suportada nativamente pelo transceiver
        ISO 9141/KWP2000 do Vgate vLinker MC+) das K-Lines multiplexadas em outros pinos
        (Pinos 1, 3, 8, 9, 11, 12, 13), prevenindo falsos diagnósticos de 'módulo morto'.
        """
        if pin == 7:
            return {
                "pin": 7,
                "supported_natively": True,
                "transceiver": "ISO 9141-2 / ISO 14230-4 K-Line Nativa (Pino 7 OBD-II + L-Line Pino 15)",
                "message": "Pino 7 suportado nativamente pelo Vgate vLinker MC+.",
            }

        pin_explanations = {
            1: (
                "Pino 1 no Vgate vLinker MC+ é dedicado ao transceiver SW-CAN (Single-Wire CAN 33.3 kbps da GM/GMLAN), "
                "NÃO a uma K-Line analógica. Em Fiat/Alfa (ABS no Pino 1), use o cabo adaptador Verde (Pino 1 -> Pino 7)."
            ),
            3: (
                "Pinos 3 e 11 no Vgate vLinker MC+ são dedicados ao transceiver diferencial MS-CAN (Medium-Speed CAN 125 kbps da Ford), "
                "NÃO a uma K-Line. Em Fiat/Alfa (Airbag no Pino 3), use o cabo adaptador Vermelho (Pino 3 -> Pino 7)."
            ),
            8: (
                "Pino 8 (K-Bus / I-Bus de Carroceria/ABS/Airbag em BMW E46/E39/E53 e Sprinter antiga) NÃO possui transceiver "
                "conectado no Vgate vLinker MC+. Use um adaptador OBD com ponte física Pino 7 <-> Pino 8."
            ),
            9: "Pino 9 (Direção Elétrica Fiat / ABS Sprinter antiga) NÃO possui transceiver K-Line no Vgate. Use cabo comutador para o Pino 7.",
            11: "Pino 11 é o par MS-CAN Low no Vgate. Para Imobilizador K-Line no Pino 11, use cabo comutador para o Pino 7.",
            12: "Pino 12 (Xenon/Chassi K-Line) NÃO possui transceiver no Vgate. Use cabo adaptador Amarelo/Roxo para o Pino 7.",
            13: "Pino 13 (Airbag Sprinter/Chassi K-Line) NÃO possui transceiver no Vgate. Use cabo comutador para o Pino 7.",
        }
        reason = pin_explanations.get(
            pin,
            f"O Pino {pin} não possui transceiver K-Line no Vgate vLinker MC+ (apenas o Pino 7 possui transceiver K-Line).",
        )
        return {
            "pin": pin,
            "supported_natively": False,
            "transceiver": "K-Line Multiplexada Externa (Fora do Pino 7)",
            "error": "HARDWARE_PIN_NOT_ROUTED_TO_KLINE_TRANSCEIVER",
            "message": reason,
        }

    # ==========================================================================
    # 3. IDENTIFICAÇÃO AUTOMÁTICA E CONFIRMAÇÃO DETERMINÍSTICA DO PROTOCOLO
    # ==========================================================================

    async def detect_and_confirm_protocol(self) -> Dict[str, Any]:
        """
        Identifica automaticamente e confirma o protocolo real do veículo sem assumir CAN a priori:
        Etapa 1: Testa CAN 11-bit 500k (ATSP6) -> CAN 29-bit 500k (ATSP7) -> CAN 250k (ATSP8).
        Etapa 2: Se CAN não responder, executa inicialização independente de K-Line no Pino 7:
                 KWP2000 Fast Init (ATSP5) -> KWP2000 5-Baud (ATSP4) -> ISO 9141-2 5-Baud (ATSP3).
        Etapa 3: Confirma com ATDP, ATDPN e (se K-Line) ATKW, registrando evidência completa.
        """
        # 1. Tentativa ordenada de barramentos CAN (rápida, ~1.5s por tentativa)
        for can_proto, label in [
            ("6", "ISO 15765-4 CAN (11-bit ID, 500 kbaud)"),
            ("7", "ISO 15765-4 CAN (29-bit ID, 500 kbaud)"),
            ("8", "ISO 15765-4 CAN (11-bit ID, 250 kbaud)"),
        ]:
            await self.cmd("ATAR", context=f"Resetar filtros antes de testar {label}")
            await self.cmd(f"ATSP{can_proto}", context=f"Testar protocolo {label}")
            self._update_protocol_state_from_code(can_proto, label)
            resp = await self.cmd("01 00", timeout=2.2, context=f"Sonda OBD 01 00 em {label}")
            if "41 00" in resp.upper() or "4100" in resp.replace(" ", "").upper():
                dp = await self.cmd("ATDP", context="Confirmar nome do protocolo CAN")
                dpn = await self.cmd("ATDPN", context="Confirmar código do protocolo CAN")
                self._update_protocol_state_from_code(dpn, dp)
                return {
                    "confirmed": True,
                    "family": self.active_protocol_family,
                    "protocol_code": self.active_protocol_code,
                    "protocol_name": self.active_protocol_name,
                    "physical_pins": self.active_physical_pins,
                    "probe_response": resp,
                }

        # 2. Se CAN falhou, executa inicialização independente para K-Line (Pino 7)
        # 2a. KWP2000 Fast Init Funcional (C1 33 F1) e Físico Motor (81 10 F1)
        kwp_fast = await self.init_kwp2000_fast(target_addr="10", functional=True, pin=7)
        if kwp_fast.get("success"):
            return {
                "confirmed": True,
                "family": "KLINE",
                "protocol_code": self.active_protocol_code,
                "protocol_name": self.active_protocol_name,
                "physical_pins": self.active_physical_pins,
                "keywords": kwp_fast.get("keywords", ""),
                "probe_response": kwp_fast.get("init_response", ""),
            }

        # 2b. KWP2000 5-Baud Init (ATSP4)
        kwp_5b = await self.init_kwp2000_5baud(target_addr="33", pin=7)
        if kwp_5b.get("success"):
            return {
                "confirmed": True,
                "family": "KLINE",
                "protocol_code": self.active_protocol_code,
                "protocol_name": self.active_protocol_name,
                "physical_pins": self.active_physical_pins,
                "keywords": kwp_5b.get("keywords", ""),
                "probe_response": kwp_5b.get("init_response", ""),
            }

        # 2c. ISO 9141-2 5-Baud Init (ATSP3 — ex: Audi A4/S4 B6 e BMW E46 em modo OBD)
        iso9141 = await self.init_iso9141_5baud(target_addr="33", pin=7)
        if iso9141.get("success"):
            return {
                "confirmed": True,
                "family": "KLINE",
                "protocol_code": self.active_protocol_code,
                "protocol_name": self.active_protocol_name,
                "physical_pins": self.active_physical_pins,
                "keywords": iso9141.get("keywords", ""),
                "probe_response": iso9141.get("init_response", ""),
            }

        return {
            "confirmed": False,
            "family": "NONE",
            "protocol_code": "0",
            "protocol_name": "NENHUM PROTOCOLO RESPONDEU (Verifique Ignição ON / Pino 7 vs Pino Multiplexado)",
            "physical_pins": "N/A",
            "probe_response": "NO DATA",
        }

    # ==========================================================================
    # GERENCIAMENTO DE ENDEREÇAMENTO SEGURO (CAN vs K-LINE)
    # ==========================================================================

    async def set_can_target(self, tx_id: str, rx_id: Optional[str] = None) -> None:
        """
        Configura endereçamento físico CAN, filtro de hardware ATCRA e Flow Control ISO-TP.
        PROTEÇÃO K-LINE: Se o protocolo ativo for K-Line (ATSP 3/4/5), NÃO envia ATCRA nem
        Flow Control CAN (ATFCSH/ATFCSD/ATFCSM), pois corromperiam o cabeçalho de 3 bytes da K-Line!
        """
        if self.is_kline:
            # Em K-Line o header tem 3 bytes (ex: '81 10 F1' ou '68 6A F1')
            hdr_clean = tx_id.strip().upper()
            await self.cmd(f"ATSH {hdr_clean}", context=f"Header K-Line ({hdr_clean})")
            self.current_tx_header = hdr_clean
            return

        tx_clean = tx_id.replace("0x", "").strip().upper()
        if not rx_id:
            if len(tx_clean) == 3 and tx_clean.startswith("7E") and tx_clean != "7DF":
                rx_clean = f"{int(tx_clean, 16) + 8:03X}"
            else:
                rx_clean = ""
        else:
            rx_clean = rx_id.replace("0x", "").strip().upper()

        await self.cmd(f"ATSH {tx_clean}", context=f"Header TX CAN ({tx_clean})")
        if rx_clean:
            await self.cmd(f"ATCRA {rx_clean}", context=f"Filtro RX Hardware CAN ({rx_clean})")
            await self.cmd(f"ATFCSH {tx_clean}", context=f"Flow Control Header CAN ({tx_clean})")
            await self.cmd("ATFCSD 300000", context="Flow Control Data (ClearToSend, BS=0, STmin=0)")
            await self.cmd("ATFCSM 1", context="Ativar Flow Control Customizado")
        else:
            await self.cmd("ATAR", context="Restaurar Auto-Receive CAN")
        self.current_tx_header = tx_clean

    async def restore_default_state(self) -> None:
        """
        Restaura o estado padrão respeitando o protocolo ativo:
        - Se estiver em K-Line (ATSP 3/4/5), mantém o header funcional K-Line sem forçar 7DF!
        - Se estiver em CAN (ATSP 6/8), limpa filtro ATCRA (ATAR) e volta para 7DF.
        """
        if self.is_kline:
            default_k_hdr = "68 6A F1" if self.active_protocol_code == "3" else (
                "C2 33 F1" if self.active_protocol_code == "4" else "C1 33 F1"
            )
            await self.cmd(f"ATSH {default_k_hdr}", context="Restaurar Header Funcional K-Line")
            self.current_tx_header = default_k_hdr
        elif self.active_protocol_family == "CAN_29B":
            await self.cmd("ATAR", context="Limpar filtro ATCRA 29-bit")
            await self.cmd("ATSH 18DB33F1", context="Restaurar Header Funcional CAN 29-bit")
            self.current_tx_header = "18DB33F1"
        else:
            await self.cmd("ATAR", context="Limpar filtro ATCRA 11-bit")
            await self.cmd("ATSH 7DF", context="Restaurar Header Funcional CAN 11-bit (7DF)")
            self.current_tx_header = "7DF"

    async def restore_broadcast(self) -> None:
        """Alias retrocompatível para restore_default_state()."""
        await self.restore_default_state()

    async def ensure_kwp_init(self, retries: int = 3) -> Tuple[bool, str]:
        """
        Inicializa barramento K-Line testando de forma independente KWP Fast Init (ATSP5),
        KWP 5-Baud (ATSP4) e ISO 9141-2 (ATSP3) sem forçar CAN.
        """
        for attempt in range(1, retries + 1):
            r_fast = await self.init_kwp2000_fast(target_addr="10", functional=True, pin=7)
            if r_fast.get("success"):
                return True, f"KWP2000 Fast Init (ATSP5) confirmado na tentativa {attempt} (KW: {r_fast.get('keywords')})"
            r_5b = await self.init_kwp2000_5baud(target_addr="33", pin=7)
            if r_5b.get("success"):
                return True, f"KWP2000 5-Baud (ATSP4) confirmado na tentativa {attempt} (KW: {r_5b.get('keywords')})"
            r_iso = await self.init_iso9141_5baud(target_addr="33", pin=7)
            if r_iso.get("success"):
                return True, f"ISO 9141-2 5-Baud (ATSP3) confirmado na tentativa {attempt} (KW: {r_iso.get('keywords')})"
            await asyncio.sleep(1.0)
        return False, "Falha ao inicializar K-Line no Pino 7 após testar ATSP5, ATSP4 e ATSP3."


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
        is_kline_hdr = len(parts) >= 5 and (
            (parts[0].startswith(("8", "C")) and parts[1] == "F1")
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


# ==============================================================================
# 2. HANDSHAKE CIRÚRGICO CORRIGIDO (NÃO FORÇA CAN QUANDO ESTIVER EM K-LINE)
# ==============================================================================

async def run_quick_handshake(vl: VLinkerBLE) -> Dict[str, Any]:
    """
    Handshake cirúrgico protocolo-consciente:
    1. Lê ATRV (Tensão da bateria no Pino 16).
    2. Identifica e confirma automaticamente o protocolo real (CAN vs K-Line ISO 9141 / KWP 5-Baud / KWP Fast).
    3. Se for CAN: aplica filtro físico ATSH 7E0 + ATCRA 7E8 e lê VIN (0902 / 22F190) + DTCs (03).
    4. Se for K-Line: NÃO envia ATSH 7E0 nem ATCRA 7E8! Mantém o barramento K-Line vivo (Pino 7) e lê
       VIN via 09 02 (com fallback KWP 1A 90 / Bloco VAG 21 81) + DTCs via Modo 03 (com fallback KWP 18 00 FF 00 / 07).
    5. Salva o Registro Pericial de Evidências automaticamente.
    """
    atrv = await vl.cmd("ATRV", context="Leitura de tensão da bateria (Pino 16 OBD-II)")

    # Se o usuário não travou um protocolo específico ou se ainda não foi confirmado, detecta automaticamente
    if vl.protocol == "0" or vl.active_protocol_name == "UNCONFIRMED":
        proto_info = await vl.detect_and_confirm_protocol()
    else:
        dp = await vl.cmd("ATDP", context="Consulta protocolo atual")
        dpn = await vl.cmd("ATDPN", context="Consulta código protocolo atual")
        vl._update_protocol_state_from_code(dpn, dp)
        proto_info = {
            "confirmed": True,
            "family": vl.active_protocol_family,
            "protocol_code": vl.active_protocol_code,
            "protocol_name": vl.active_protocol_name,
            "physical_pins": vl.active_physical_pins,
        }

    if vl.is_kline:
        # MODO K-LINE (ISO 9141-2 / KWP2000) — PROIBIDO USAR ATSH 7E0 / ATCRA 7E8!
        r_vin = await vl.cmd("09 02", timeout=5.0, context="Leitura de VIN Modo 09 02 em K-Line")
        if any(err in r_vin.upper() for err in ("NO DATA", "ERROR", "7F", "?")):
            # Fallback KWP2000 ReadEcuIdentification (1A 90 = VIN, 1A 9B = VAG Part Number)
            r_vin_kwp = await vl.cmd("1A 90", timeout=4.0, context="Fallback VIN KWP2000 (1A 90)")
            if "5A 90" in r_vin_kwp.upper() or "5A90" in r_vin_kwp.replace(" ", "").upper():
                r_vin = r_vin_kwp
            else:
                r_id_kwp = await vl.cmd("1A 9B", timeout=4.0, context="Fallback Identificação ECU KWP2000 (1A 9B)")
                if "5A 9B" in r_id_kwp.upper():
                    r_vin = f"[ECU ID KWP 1A9B] {r_id_kwp}"

        r_dtc = await vl.cmd("03", timeout=5.0, context="Leitura de DTCs Modo 03 em K-Line")
        if any(err in r_dtc.upper() for err in ("NO DATA", "ERROR", "7F")):
            # Fallback KWP2000 ReadDiagnosticTroubleCodesByStatus (18 00 FF 00)
            r_dtc_kwp = await vl.cmd("18 00 FF 00", timeout=4.0, context="Fallback DTCs KWP2000 (18 00 FF 00)")
            if "58" in r_dtc_kwp.upper():
                r_dtc = r_dtc_kwp
    else:
        # MODO CAN (ISO 15765-4 11-bit / 29-bit)
        if vl.active_protocol_family == "CAN_29B":
            await vl.set_can_target("18DA10F1", "18DAF110")
        else:
            await vl.set_can_target("7E0", "7E8")

        r_vin = await vl.cmd("09 02", timeout=3.5, context="Leitura de VIN Modo 09 02 em CAN")
        if any(err in r_vin.upper() for err in ("NO DATA", "ERROR", "7F")):
            r_vin = await vl.cmd("22 F1 90", timeout=3.5, context="Fallback VIN UDS (22 F1 90) em CAN")
        r_dtc = await vl.cmd("03", timeout=3.5, context="Leitura de DTCs Modo 03 em CAN")
        await vl.restore_default_state()

    ev_path = vl.save_evidence_report("handshake_evidence")

    print("=" * 76)
    print("🩺 HANDSHAKE CIRÚRGICO PERICIAL (PROTOCOLO-CONSCIENTE)")
    print("=" * 76)
    print(f"🔋 Tensão OBD-II (ATRV)   : {atrv}")
    print(f"📡 Protocolo Confirmado   : [{vl.active_protocol_code}] {vl.active_protocol_name} ({vl.active_protocol_family})")
    print(f"🔌 Pinos Físicos Ativos   : {vl.active_physical_pins}")
    print(f"🆔 Resposta VIN / ID ECU  : {r_vin}")
    print(f"🚨 DTCs Motor (Modo 03/KWP): {r_dtc}")
    print(f"📑 Registro de Evidências : {ev_path}")
    print("=" * 76)

    return {
        "battery_voltage": atrv,
        "protocol": proto_info,
        "vin_raw": r_vin,
        "dtc_raw": r_dtc,
        "evidence_file": str(ev_path),
    }


# ==============================================================================
# 4. TESTES INDEPENDENTES DE CAN E K-LINE (COM EVIDÊNCIA PERICIAL)
# ==============================================================================

async def run_independent_can_test(vl: VLinkerBLE) -> Dict[str, Any]:
    """
    Executa bateria de teste 100% isolada para barramento CAN (Pinos 6 e 14):
    - Testa CAN 11-bit 500kbps (ATSP6) com filtro físico 7E0 -> 7E8
    - Testa CAN 29-bit 500kbps (ATSP7) com filtro físico 18DA10F1 -> 18DAF110
    - Testa CAN 11-bit 250kbps (ATSP8)
    """
    print("\n🔬 [TESTE INDEPENDENTE DE BARRAMENTO CAN — PINOS 6 (CAN-H) / 14 (CAN-L)]")
    print("=" * 76)
    atrv = await vl.cmd("ATRV", context="Tensão antes do teste independente CAN")
    results: Dict[str, Any] = {"battery": atrv, "tests": []}

    can_suites = [
        ("6", "ISO 15765-4 CAN 11-bit 500 kbps", "7E0", "7E8"),
        ("7", "ISO 15765-4 CAN 29-bit 500 kbps", "18DA10F1", "18DAF110"),
        ("8", "ISO 15765-4 CAN 11-bit 250 kbps", "7E0", "7E8"),
    ]

    for proto_code, desc, tx_id, rx_id in can_suites:
        await vl.cmd("ATAR", context=f"Limpar filtros antes de {desc}")
        await vl.cmd(f"ATSP{proto_code}", context=f"Selecionar {desc}")
        vl._update_protocol_state_from_code(proto_code, desc)
        await vl.set_can_target(tx_id, rx_id)

        r_obd = await vl.cmd("01 00", timeout=2.2, context=f"Teste OBD 01 00 em {desc}")
        r_uds = await vl.cmd("10 03", timeout=2.0, context=f"Teste Sessão UDS 10 03 em {desc}")
        dp = await vl.cmd("ATDP", context="Confirmar protocolo no chip")
        ok = any("41 00" in x.upper() or "50 03" in x.upper() or "7F 10" in x.upper() for x in (r_obd, r_uds))

        status_icon = "✅ ATIVO" if ok else "⚪ SEM RESPOSTA"
        print(f"{status_icon} | ATSP{proto_code} ({desc}) [{tx_id} -> {rx_id}]")
        print(f"          • 01 00 (OBD) : {r_obd}")
        print(f"          • 10 03 (UDS) : {r_uds}")
        results["tests"].append(
            {
                "atsp": proto_code,
                "description": desc,
                "tx_id": tx_id,
                "rx_id": rx_id,
                "obd_0100": r_obd,
                "uds_1003": r_uds,
                "atdp": dp,
                "active": ok,
            }
        )

    await vl.restore_default_state()
    ev_path = vl.save_evidence_report("independent_can_test")
    print(f"\n📑 Evidência Pericial CAN salva em: {ev_path}")
    return results


async def run_independent_kline_test(
    vl: VLinkerBLE, target_addr: str = "10", pin: int = 7
) -> Dict[str, Any]:
    """
    Executa bateria de teste 100% isolada para barramento K-Line:
    1. Valida se o pino solicitado é o Pino 7 (nativo) ou um pino multiplexado externo (1, 3, 8, 9, 11, 12, 13).
    2. Testa de forma independente:
       - KWP2000 Fast Init (ATSP5) — Funcional (C1 33 F1) e Físico (81 <target> F1)
       - KWP2000 5-Baud Init (ATSP4) — Funcional (C2 33 F1)
       - ISO 9141-2 5-Baud Init (ATSP3) — Funcional (68 6A F1)
    """
    print(f"\n🔬 [TESTE INDEPENDENTE DE BARRAMENTO K-LINE — PINO {pin} | ALVO 0x{target_addr.upper()}]")
    print("=" * 76)
    pin_check = vl.verify_kline_pin_capability(pin)
    if not pin_check["supported_natively"]:
        print(f"⚠️ BLOQUEIO DE HARDWARE DETECTADO NO PINO {pin}:")
        print(f"   • Transceiver : {pin_check['transceiver']}")
        print(f"   • Diagnóstico : {pin_check['message']}")
        ev_path = vl.save_evidence_report(f"kline_pin{pin}_blocked")
        print(f"📑 Evidência Pericial salva em: {ev_path}")
        return pin_check

    atrv = await vl.cmd("ATRV", context="Tensão antes do teste independente K-Line")
    print(f"🔋 Tensão OBD-II (ATRV): {atrv}")

    # Teste 1: KWP2000 Fast Init Físico (81 <target> F1)
    print(f"\n[1/4] Testando KWP2000 Fast Init Físico (ATSP5 | Header 81 {target_addr.upper()} F1)...")
    res_fast_phys = await vl.init_kwp2000_fast(target_addr=target_addr, functional=False, pin=pin)
    print(f"      ➔ Resultado: {'✅ SUCESSO' if res_fast_phys['success'] else '⚪ SEM RESPOSTA'} | Resp: {res_fast_phys['init_response']} | KW: {res_fast_phys['keywords']}")

    # Teste 2: KWP2000 Fast Init Funcional (C1 33 F1)
    print("\n[2/4] Testando KWP2000 Fast Init Funcional (ATSP5 | Header C1 33 F1)...")
    res_fast_func = await vl.init_kwp2000_fast(target_addr="33", functional=True, pin=pin)
    print(f"      ➔ Resultado: {'✅ SUCESSO' if res_fast_func['success'] else '⚪ SEM RESPOSTA'} | Resp: {res_fast_func['init_response']} | KW: {res_fast_func['keywords']}")

    # Teste 3: KWP2000 5-Baud Init (ATSP4 | Header C2 33 F1)
    print("\n[3/4] Testando KWP2000 5-Baud Init (ATSP4 | Header C2 33 F1)...")
    res_kwp_5b = await vl.init_kwp2000_5baud(target_addr="33", pin=pin)
    print(f"      ➔ Resultado: {'✅ SUCESSO' if res_kwp_5b['success'] else '⚪ SEM RESPOSTA'} | Resp: {res_kwp_5b['init_response']} | KW: {res_kwp_5b['keywords']}")

    # Teste 4: ISO 9141-2 5-Baud Init (ATSP3 | Header 68 6A F1)
    print("\n[4/4] Testando ISO 9141-2 5-Baud Init (ATSP3 | Header 68 6A F1)...")
    res_iso9141 = await vl.init_iso9141_5baud(target_addr="33", pin=pin)
    print(f"      ➔ Resultado: {'✅ SUCESSO' if res_iso9141['success'] else '⚪ SEM RESPOSTA'} | Resp: {res_iso9141['init_response']} | KW: {res_iso9141['keywords']}")

    ev_path = vl.save_evidence_report("independent_kline_test")
    print(f"\n📑 Evidência Pericial K-Line salva em: {ev_path}")
    return {
        "battery": atrv,
        "pin": pin,
        "kwp_fast_physical": res_fast_phys,
        "kwp_fast_functional": res_fast_func,
        "kwp_5baud": res_kwp_5b,
        "iso9141_5baud": res_iso9141,
        "evidence_file": str(ev_path),
    }


def print_kline_pin_topology_guide() -> None:
    """Exibe o mapa pericial separando K-Line no Pino 7 de K-Line multiplexada em outros pinos."""
    print("\n📌 MAPA DE ARQUITETURA K-LINE: PINO 7 NATIVO vs PINOS MULTIPLEXADOS EXTERNOS")
    print("=" * 80)
    for key, info in KLINE_PIN_TOPOLOGY.items():
        print(f"\n🚗 Família: {key.upper()} — {info['vehicle_examples']}")
        print("   ✅ Módulos no PINO 7 (Suportados Nativamente pelo Vgate vLinker MC+):")
        for m in info["pin_7_modules"]:
            print(f"      • {m['name']} [Alvo 0x{m['target_addr']} | Fast: '{m['hdr_fast']}' | Func: '{m['hdr_func']}']")
        print("   ⚠️ Módulos em K-LINE MULTIPLEXADA (Fora do Pino 7 — Exigem Cabo Ponte/Multiplexador):")
        for mx in info["multiplexed_non_pin7_modules"]:
            print(f"      • {mx['name']} -> {mx['obd_pin']}")
            print(f"        Motivo/Solução: {mx['hardware_requirement']}")
    print("=" * 80)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente BLE Vgate vLinker MC+ (Arquitetura Pericial CAN + K-Line) — AgentCarDiag")
    parser.add_argument("--proto", default="0", help="Protocolo ATSP (0=Auto-Detect, 3=ISO9141 5-Baud, 4=KWP 5-Baud, 5=KWP Fast, 6=CAN 11b 500k, 7=CAN 29b 500k)")
    parser.add_argument("--tx", default="", help="Header TX físico opcional (CAN: 7E0, 713, 645 | K-Line: '81 10 F1', '68 6A F1')")
    parser.add_argument("--rx", default="", help="Filtro RX físico opcional (apenas CAN: 7E8, 77D, 5C5)")
    parser.add_argument("--handshake", action="store_true", help="Executa o Handshake Cirúrgico Protocolo-Consciente (não força CAN em K-Line)")
    parser.add_argument("--detect-protocol", action="store_true", help="Identifica automaticamente e confirma o protocolo real (CAN vs K-Line)")
    parser.add_argument("--test-can", action="store_true", help="Executa teste independente de barramento CAN (Pinos 6/14)")
    parser.add_argument("--test-kline", action="store_true", help="Executa teste independente de barramento K-Line (ISO 9141, KWP 5-Baud, KWP Fast)")
    parser.add_argument("--init-iso9141", action="store_true", help="Inicializa exclusivamente ISO 9141-2 5-Baud (ATSP3)")
    parser.add_argument("--init-kwp-5baud", action="store_true", help="Inicializa exclusivamente KWP2000 5-Baud (ATSP4)")
    parser.add_argument("--init-kwp-fast", action="store_true", help="Inicializa exclusivamente KWP2000 Fast Init (ATSP5)")
    parser.add_argument("--kline-addr", default="10", help="Endereço físico do módulo K-Line em hex (default: 10=Motor, 28=ABS VAG, 58=Airbag VAG, 12=DME BMW)")
    parser.add_argument("--kline-pin", type=int, default=7, help="Pino OBD-II da K-Line do módulo (default: 7; alerta se for pino multiplexado 1, 3, 8, 9, 12, 13)")
    parser.add_argument("--show-kline-pins", action="store_true", help="Exibe tabela técnica separando K-Line Pino 7 de K-Line multiplexada em outros pinos")
    parser.add_argument("cmds", nargs="*", help="Comandos AT/OBD/UDS/KWP a enviar")
    args = parser.parse_args()

    if args.show_kline_pins:
        print_kline_pin_topology_guide()
        if not any([args.handshake, args.detect_protocol, args.test_can, args.test_kline, args.init_iso9141, args.init_kwp_5baud, args.init_kwp_fast, args.cmds]):
            return

    async with VLinkerBLE(protocol=args.proto) as vl:
        if args.handshake:
            await run_quick_handshake(vl)
            return

        if args.detect_protocol:
            res = await vl.detect_and_confirm_protocol()
            ev_path = vl.save_evidence_report("protocol_detection")
            print(json.dumps(res, indent=2, ensure_ascii=False))
            print(f"📑 Evidência salva em: {ev_path}")
            return

        if args.test_can:
            await run_independent_can_test(vl)
            return

        if args.test_kline:
            await run_independent_kline_test(vl, target_addr=args.kline_addr, pin=args.kline_pin)
            return

        if args.init_iso9141:
            res = await vl.init_iso9141_5baud(target_addr=args.kline_addr, pin=args.kline_pin)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.init_kwp_5baud:
            res = await vl.init_kwp2000_5baud(target_addr=args.kline_addr, pin=args.kline_pin)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.init_kwp_fast:
            res = await vl.init_kwp2000_fast(target_addr=args.kline_addr, functional=(args.kline_addr == "33"), pin=args.kline_pin)
            print(json.dumps(res, indent=2, ensure_ascii=False))

        if args.tx:
            await vl.set_can_target(args.tx, args.rx or None)

        if args.cmds:
            for c in args.cmds:
                res = await vl.cmd(c, context="Comando manual via CLI")
                print(f"[{c}] => {res}")
            ev_path = vl.save_evidence_report("cli_commands")
            print(f"\n📑 Registro de Evidência salvo em: {ev_path}")


if __name__ == "__main__":
    asyncio.run(main())
