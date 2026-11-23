#!/usr/bin/env python3
"""
full_vehicle_scan.py — Catálogo e Scanner Cirúrgico Multi-Módulos CAN/UDS + K-Line (Pino 7 vs Multiplexado)
Projeto AgentCarDiag

Suporta varredura sob demanda com:
  1. Identificação e confirmação automática do protocolo (CAN vs K-Line)
  2. Varredura CAN 11-bit com filtro físico estrito (ATSH + ATCRA + Flow Control)
  3. Varredura K-Line independente (ISO 9141-2, KWP 5-Baud, KWP Fast Init) separando
     explicitamente os módulos no Pino 7 (suportados nativamente pelo Vgate vLinker MC+)
     dos módulos em K-Line multiplexada em outros pinos (Pinos 1, 3, 8, 9, 11, 12, 13)
  4. Geração automática de Registro Pericial de Evidências (JSON)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Dict, List, Tuple

from vlinker_diag import KLINE_PIN_TOPOLOGY, VLinkerBLE

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


async def probe_can_module(vl: VLinkerBLE, name: str, tx_id: str, rx_id: str) -> Dict[str, object]:
    """
    Sonda um módulo CAN específico com filtro físico ATCRA (evita BUFFER FULL),
    tenta identificação UDS (22 F187 / F189 / F197 / F111) ou KWP Renault (10C0 + 2180),
    e lê DTCs UDS (19 02 FF) com fallback para KWP (17 FF 00).
    """
    await vl.set_can_target(tx_id, rx_id)

    r_sess = await vl.cmd("10 03", timeout=1.8, context=f"Sessão UDS 10 03 [{name}]")
    r_pn = await vl.cmd("22 F1 87", timeout=1.8, context=f"Leitura Part Number UDS 22 F1 87 [{name}]")
    if "NO DATA" in r_pn.upper() or "7F" in r_pn.upper():
        r_pn_mb = await vl.cmd("22 F1 11", timeout=1.5, context=f"Fallback Daimler HW 22 F1 11 [{name}]")
        if "62 F1 11" in r_pn_mb.upper() or "62F111" in r_pn_mb.replace(" ", "").upper():
            r_pn = r_pn_mb
        else:
            await vl.cmd("10 C0", timeout=1.2, context=f"Sessão KWP-on-CAN 10 C0 [{name}]")
            r_kwp_id = await vl.cmd("21 80", timeout=1.5, context=f"Identificação KWP 21 80 [{name}]")
            if "61 80" in r_kwp_id.upper() or "6180" in r_kwp_id.replace(" ", "").upper():
                r_pn = r_kwp_id

    r_sw = await vl.cmd("22 F1 89", timeout=1.5, context=f"Leitura SW Version 22 F1 89 [{name}]")
    r_sys = await vl.cmd("22 F1 97", timeout=1.5, context=f"Leitura System Name 22 F1 97 [{name}]")

    r_dtc = await vl.cmd("19 02 FF", timeout=2.5, context=f"Leitura DTCs UDS 19 02 FF [{name}]")
    if "NO DATA" in r_dtc.upper() or "7F 19" in r_dtc.upper():
        r_dtc_kwp = await vl.cmd("17 FF 00", timeout=2.0, context=f"Fallback DTCs KWP 17 FF 00 [{name}]")
        if "57" in r_dtc_kwp.upper():
            r_dtc = r_dtc_kwp

    alive = not all("NO DATA" in x.upper() or not x.strip() for x in (r_sess, r_pn, r_sw, r_sys, r_dtc))
    return {
        "module": name,
        "bus": "CAN (Pinos 6/14)",
        "tx_id": tx_id,
        "rx_id": rx_id,
        "alive": alive,
        "session_resp": r_sess,
        "part_number_raw": r_pn,
        "sw_version_raw": r_sw,
        "system_name_raw": r_sys,
        "dtcs_raw": r_dtc,
    }


async def probe_kline_pin7_module(vl: VLinkerBLE, mod_entry: Dict[str, str]) -> Dict[str, Any]:
    """
    Sonda um módulo K-Line nativo no Pino 7 testando primeiro KWP2000 Fast Init (ATSP5)
    e, se necessário, KWP2000 5-Baud Init (ATSP4), lendo identificação KWP (1A 9B / 1A 80)
    e DTCs (18 00 FF 00 / Modo 03).
    """
    name = mod_entry["name"]
    addr = mod_entry["target_addr"]

    init_res = await vl.init_kwp2000_fast(target_addr=addr, functional=False, pin=7)
    if not init_res.get("success"):
        init_res = await vl.init_kwp2000_5baud(target_addr=addr, pin=7)

    if not init_res.get("success"):
        return {
            "module": name,
            "bus": "K-Line Pino 7 (Nativo)",
            "target_addr": addr,
            "alive": False,
            "protocol_used": init_res.get("protocol", "K-Line"),
            "part_number_raw": "NO DATA",
            "dtcs_raw": "NO DATA",
        }

    # Identificação KWP2000 (1A 9B VAG Part Number / 1A 80 Identificação Geral)
    r_id = await vl.cmd("1A 9B", timeout=3.5, context=f"Identificação KWP 1A 9B [{name}]")
    if "NO DATA" in r_id.upper() or "7F" in r_id.upper():
        r_id = await vl.cmd("1A 80", timeout=3.5, context=f"Identificação KWP 1A 80 [{name}]")

    # Leitura de DTCs KWP2000 (18 00 FF 00) com fallback para OBD Modo 03
    r_dtc = await vl.cmd("18 00 FF 00", timeout=4.0, context=f"Leitura DTCs KWP 18 00 FF 00 [{name}]")
    if "NO DATA" in r_dtc.upper() or "7F" in r_dtc.upper():
        r_dtc = await vl.cmd("03", timeout=4.0, context=f"Fallback DTCs Modo 03 [{name}]")

    return {
        "module": name,
        "bus": "K-Line Pino 7 (Nativo)",
        "target_addr": addr,
        "alive": True,
        "protocol_used": vl.active_protocol_name,
        "keywords": init_res.get("keywords", ""),
        "part_number_raw": r_id,
        "dtcs_raw": r_dtc,
    }


async def run_kline_scan(kline_family: str) -> None:
    topo = KLINE_PIN_TOPOLOGY[kline_family]
    pin7_mods = topo["pin_7_modules"]
    mux_mods = topo["multiplexed_non_pin7_modules"]

    print(f"🔍 Iniciando Varredura K-Line Independente (Família: {kline_family} — {topo['vehicle_examples']})...")
    results = []
    async with VLinkerBLE(protocol="5") as vl:
        atrv = await vl.cmd("ATRV", context="Tensão da bateria antes da varredura K-Line")
        print(f"🔋 Tensão da Bateria (ATRV): {atrv}\n")

        print("=== [1] MÓDULOS K-LINE NO PINO 7 (SUPORTADOS NATIVAMENTE PELO VGATE) ===")
        for mod in pin7_mods:
            info = await probe_kline_pin7_module(vl, mod)
            if info["alive"]:
                print(f"✅ [Pino 7 | Alvo 0x{info['target_addr']}] {info['module']} ({info['protocol_used']})")
                print(f"   • ID/PN : {info['part_number_raw']}")
                print(f"   • DTCs  : {info['dtcs_raw']}\n")
                results.append(info)
            else:
                print(f"⚪ [Pino 7 | Alvo 0x{info['target_addr']}] {info['module']}: Sem resposta no Pino 7")

        print("\n=== [2] MÓDULOS EM K-LINE MULTIPLEXADA (FORA DO PINO 7 — AVISO DE HARDWARE) ===")
        for mx in mux_mods:
            print(f"⚠️ [{mx['obd_pin']}] {mx['name']}")
            print(f"   • Status no Vgate : BLOQUEADO FISICAMENTE (Sem transceiver K-Line neste pino)")
            print(f"   • Solução Exigida : {mx['hardware_requirement']}\n")

        ev_path = vl.save_evidence_report(f"kline_scan_{kline_family}")
        print(f"📊 Resumo Pino 7: {len(results)}/{len(pin7_mods)} módulos K-Line responderam.")
        print(f"📑 Registro Pericial de Evidências salvo em: {ev_path}")


async def run_scan(profile: str) -> None:
    if profile in KLINE_PIN_TOPOLOGY:
        await run_kline_scan(profile)
        return

    modules = MODULE_CATALOG_11BIT.get(profile, MODULE_CATALOG_11BIT["powertrain"])
    print(f"🔍 Iniciando Varredura Cirúrgica Multi-Módulos CAN (Perfil: {profile} | {len(modules)} módulos)...")
    results = []
    async with VLinkerBLE(protocol="6") as vl:
        atrv = await vl.cmd("ATRV", context="Tensão da bateria antes da varredura CAN")
        print(f"🔋 Tensão da Bateria (ATRV): {atrv}\n")
        for name, tx_id, rx_id in modules:
            info = await probe_can_module(vl, name, tx_id, rx_id)
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
        await vl.restore_default_state()
        ev_path = vl.save_evidence_report(f"can_scan_{profile}")

    print(f"\n📊 Resumo: {len(results)}/{len(modules)} módulos responderam ativamente.")
    print(f"📑 Registro Pericial de Evidências salvo em: {ev_path}")


def main() -> None:
    all_profiles = list(MODULE_CATALOG_11BIT.keys()) + list(KLINE_PIN_TOPOLOGY.keys())
    parser = argparse.ArgumentParser(description="Scanner Multi-Módulos Cirúrgico (CAN & K-Line) — AgentCarDiag")
    parser.add_argument(
        "--profile",
        choices=all_profiles,
        default="powertrain",
        help="Família de módulos CAN ou K-Line a sondar",
    )
    args = parser.parse_args()
    asyncio.run(run_scan(args.profile))


if __name__ == "__main__":
    main()
