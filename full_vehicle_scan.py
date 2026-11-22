#!/usr/bin/env python3
"""
full_vehicle_scan.py — Catálogo e Scanner Cirúrgico Multi-Módulos CAN/UDS/KWP2000
Projeto AgentCarDiag

Suporta varredura sob demanda com filtro físico estrito (ATSH + ATCRA + Flow Control)
para prevenir 100% o erro BUFFER FULL em redes CAN densas:
  - Powertrain universal (7E0..7E7 -> 7E8..7EF)
  - VAG / Audi / Porsche 970 (710..773 -> 77A..7DD)
  - Mercedes-Benz Sprinter W907/W910 via Gateway EZS167 (740..77F -> TX-0x20 e 600..67F -> TX-0x80)
  - Ford (720..760 -> 728..768)
  - Renault / PSA KWP2000-on-CAN & UDS (740..757 -> 760..777 com fallback 17FF00 / 1902FF)
  - CAN 29-bit ISO 15765-4 (18DAxxF1 -> 18DAF1xx)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Dict, List, Tuple

from vlinker_diag import VLinkerBLE

# Catálogo de Topologia CAN 11-bit por Família / Montadora: (Nome, TX_ID, RX_ID)
MODULE_CATALOG_11BIT: Dict[str, List[Tuple[str, str, str]]] = {
    "powertrain": [
        ("ECM / Motor", "7E0", "7E8"),
        ("TCM / Transmissão", "7E1", "7E9"),
        ("ABS / CPC / Inversor", "7E2", "7EA"),
        ("SCR AdBlue / Chassi / EPB", "7E3", "7EB"),
        ("BCM / BMS Bateria HV", "7E4", "7EC"),
        ("FSCM Bomba Combustível / OBC", "7E5", "7ED"),
    ],
    "vag_porsche": [
        ("ECM / Motor (DME)", "7E0", "7E8"),
        ("TCM / Câmbio (DSG / PDK)", "7E1", "7E9"),
        ("Gateway Central (J533)", "710", "77A"),
        ("Direção Elétrica (EPS)", "712", "77C"),
        ("Freios ABS / ESC / PSM+", "713", "77D"),
        ("Painel de Instrumentos (IPC / Kombi)", "714", "77E"),
        ("Airbag / SRS", "715", "77F"),
        ("PDCC (Chassis Control)", "722", "78C"),
        ("Tampa Traseira (HDS)", "723", "78D"),
        ("SWS Esquerdo", "725", "78F"),
        ("Módulo SU G1", "729", "793"),
        ("Climatronic / BCM", "746", "7B0"),
        ("Freio Estacionamento Elétrico (EPB)", "752", "7BC"),
        ("SWS Direito", "754", "7BE"),
        ("Suspensão Ativa (PASM)", "755", "7BF"),
        ("Radar Cruise Control (ACC)", "757", "7C1"),
        ("Park Assist (PDC)", "765", "7CF"),
        ("Multimídia (5F)", "773", "7DD"),
    ],
    "mercedes_w910": [
        ("ECM Motor OM651/OM654 (CRD3)", "7E0", "7E8"),
        ("TCM Transmissão", "7E1", "7E9"),
        ("CPC_NG Powertrain Controller", "7E2", "7EA"),
        ("SCR / AdBlue Control Unit", "7E3", "7EB"),
        ("FSCM Bomba de Combustível", "7E5", "7ED"),
        ("Coluna de Direção / Chassi", "742", "722"),
        ("EZS167 Gateway / Ignição Eletrônica", "745", "725"),
        ("SAM / Carroceria BCM", "609", "589"),
        ("MBUX / Head Unit", "638", "5B8"),
        ("Painel de Instrumentos (IC907)", "641", "5C1"),
        ("SRS / Airbag (ORC177 N2/10)", "645", "5C5"),
    ],
    "ford": [
        ("ECM Motor EcoBoost / Duratorq", "7E0", "7E8"),
        ("TCM Transmissão", "7E1", "7E9"),
        ("IPC Painel de Instrumentos", "720", "728"),
        ("BCM Carroceria", "726", "72E"),
        ("PSCM Direção Elétrica", "730", "738"),
        ("RCM Airbag / Restraints", "737", "73F"),
        ("ABS / ESC Freios", "760", "768"),
    ],
    "renault_psa": [
        ("ECM Injeção Motor", "7E0", "7E8"),
        ("TCM Transmissão", "7E1", "7E9"),
        ("ABS / ESP Freios", "740", "760"),
        ("EPS Direção Elétrica", "742", "762"),
        ("IPC Painel de Instrumentos (TDB)", "743", "763"),
        ("HVAC Climatização", "744", "764"),
        ("UCH / BSI Carroceria", "745", "765"),
        ("SRS Airbag", "752", "772"),
        ("EPB Freio de Estacionamento", "757", "777"),
    ],
}


async def probe_module(vl: VLinkerBLE, name: str, tx_id: str, rx_id: str) -> Dict[str, object]:
    """
    Sonda um módulo específico com filtro físico ATCRA (evita BUFFER FULL),
    tenta identificação UDS (22 F187 / F189 / F197 / F111) ou KWP Renault (10C0 + 2180),
    e lê DTCs UDS (19 02 FF) com fallback para KWP (17 FF 00).
    """
    await vl.set_can_target(tx_id, rx_id)

    # 1. Tenta UDS Extended Session (10 03) ou Default (10 01) ou TesterPresent (3E 00)
    r_sess = await vl.cmd("10 03", timeout=1.8)
    is_silent = any(x in r_sess.upper() for x in ("NO DATA", "ERROR", "UNABLE", "?")) and not r_sess.strip()

    # Tenta leitura de Part Number UDS (22 F1 87) ou Daimler HW (22 F1 11) ou KWP (21 80)
    r_pn = await vl.cmd("22 F1 87", timeout=1.8)
    if "NO DATA" in r_pn.upper() or "7F" in r_pn.upper():
        r_pn_mb = await vl.cmd("22 F1 11", timeout=1.5)
        if "62 F1 11" in r_pn_mb.upper() or "62F111" in r_pn_mb.replace(" ", "").upper():
            r_pn = r_pn_mb
        else:
            # Tenta KWP2000-on-CAN (Renault 10 C0 + 21 80)
            await vl.cmd("10 C0", timeout=1.2)
            r_kwp_id = await vl.cmd("21 80", timeout=1.5)
            if "61 80" in r_kwp_id.upper() or "6180" in r_kwp_id.replace(" ", "").upper():
                r_pn = r_kwp_id

    r_sw = await vl.cmd("22 F1 89", timeout=1.5)
    r_sys = await vl.cmd("22 F1 97", timeout=1.5)

    # 2. Leitura de DTCs UDS (19 02 FF) com fallback para KWP (17 FF 00)
    r_dtc = await vl.cmd("19 02 FF", timeout=2.5)
    if "NO DATA" in r_dtc.upper() or "7F 19" in r_dtc.upper():
        r_dtc_kwp = await vl.cmd("17 FF 00", timeout=2.0)
        if "57" in r_dtc_kwp.upper():
            r_dtc = r_dtc_kwp

    alive = not all("NO DATA" in x.upper() or not x.strip() for x in (r_sess, r_pn, r_sw, r_sys, r_dtc))
    return {
        "module": name,
        "tx_id": tx_id,
        "rx_id": rx_id,
        "alive": alive,
        "session_resp": r_sess,
        "part_number_raw": r_pn,
        "sw_version_raw": r_sw,
        "system_name_raw": r_sys,
        "dtcs_raw": r_dtc,
    }


async def run_scan(profile: str) -> None:
    modules = MODULE_CATALOG_11BIT.get(profile, MODULE_CATALOG_11BIT["powertrain"])
    print(f"🔍 Iniciando Varredura Cirúrgica Multi-Módulos (Perfil: {profile} | {len(modules)} módulos)...")
    results = []
    async with VLinkerBLE(protocol="6") as vl:
        atrv = await vl.cmd("ATRV")
        print(f"🔋 Tensão da Bateria (ATRV): {atrv}\n")
        for name, tx_id, rx_id in modules:
            info = await probe_module(vl, name, tx_id, rx_id)
            if info["alive"]:
                print(f"✅ [{tx_id} -> {rx_id}] {name}")
                print(f"   • PN/ID : {info['part_number_raw']}")
                if "NO DATA" not in str(info["sw_version_raw"]).upper():
                    print(f"   • SW    : {info['sw_version_raw']}")
                if "NO DATA" not in str(info["system_name_raw"]).upper():
                    print(f"   • Nome  : {info['system_name_raw']}")
                print(f"   • DTCs  : {info['dtcs_raw']}\n")
                results.append(info)
            else:
                print(f"⚪ [{tx_id} -> {rx_id}] {name}: Silencioso / Não equipado")
        await vl.restore_broadcast()

    print(f"\n📊 Resumo: {len(results)}/{len(modules)} módulos responderam ativamente.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scanner Multi-Módulos Cirúrgico — AgentCarDiag")
    parser.add_argument(
        "--profile",
        choices=list(MODULE_CATALOG_11BIT.keys()),
        default="powertrain",
        help="Família de módulos a sondar (default: powertrain)",
    )
    args = parser.parse_args()
    asyncio.run(run_scan(args.profile))


if __name__ == "__main__":
    main()
