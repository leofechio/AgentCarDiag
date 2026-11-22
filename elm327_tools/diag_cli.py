#!/usr/bin/env python3
"""
AgentCarDiag — Suite Especialista de Diagnóstico Automotivo (Otimizada para Vgate vLinker MC+)
Integra:
  - Bluetooth Clássico RFCOMM (vLinker MC-Android / vLinker MC+) & BLE 4.0 (vLinker MC-IOS)
  - Comandos Estendidos AT (ELM327 v2.2/v2.3) + ST (STN / MIC3322: HS-CAN, MS-CAN, SW-CAN, K-Line)
  - Decodificador VIN Híbrido (server/app/vin_decoder.py)
  - Catálogo Offline de +2.060 DTCs (server/app/databases/dtc_database.json)
  - Manuais de Oficina & Valores de Referência OE (server/app/databases/workshop_repair_manuals.json)
  - Varredura UDS Multi-Módulo (0x19 02 FF) + OBD-II (Modos 01, 02 Freeze Frame, 03, 04, 07, 09, 0A)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elm327_core import ELM327Connection
from bt_scanner import scan_bluetooth_devices, pair_bluetooth_elm

DTC_DB_PATH = BASE_DIR / "server" / "app" / "databases" / "dtc_database.json"
MANUALS_DB_PATH = BASE_DIR / "server" / "app" / "databases" / "workshop_repair_manuals.json"


def load_dtc_db() -> Dict[str, str]:
    if DTC_DB_PATH.exists():
        try:
            with open(DTC_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


DTC_DB = load_dtc_db()


def lookup_dtc_description(code: str) -> str:
    clean = code.split("(")[0].strip().upper()
    if clean in DTC_DB:
        val = DTC_DB[clean]
        if isinstance(val, dict):
            return val.get("description_pt") or val.get("description") or str(val)
        return str(val)
    return "Código específico da montadora / Consultar boletim técnico da ECU"


# ==============================================================================
# DECODIFICADORES OBD-II (SAE J1979) & UDS (ISO 14229)
# ==============================================================================

PID_FORMULAS: Dict[str, Tuple[str, str, Any]] = {
    "04": ("Carga Calculada do Motor (Load)", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "05": ("Temperatura do Líquido de Arrefecimento (ECT)", "°C", lambda b: b[0] - 40),
    "06": ("Ajuste de Combustível Curto Prazo B1 (STFT1)", "%", lambda b: round((b[0] - 128) * 100.0 / 128.0, 2)),
    "07": ("Ajuste de Combustível Longo Prazo B1 (LTFT1)", "%", lambda b: round((b[0] - 128) * 100.0 / 128.0, 2)),
    "08": ("Ajuste de Combustível Curto Prazo B2 (STFT2)", "%", lambda b: round((b[0] - 128) * 100.0 / 128.0, 2)),
    "09": ("Ajuste de Combustível Longo Prazo B2 (LTFT2)", "%", lambda b: round((b[0] - 128) * 100.0 / 128.0, 2)),
    "0A": ("Pressão de Combustível (Linha Baixa)", "kPa", lambda b: b[0] * 3),
    "0B": ("Pressão Absoluta do Coletor (MAP)", "kPa", lambda b: b[0]),
    "0C": ("Rotação do Motor (RPM)", "RPM", lambda b: round(((b[0] * 256) + b[1]) / 4.0, 0)),
    "0D": ("Velocidade do Veículo (VSS)", "km/h", lambda b: b[0]),
    "0E": ("Avanço de Ignição (Timing Advance)", "° APMS", lambda b: round((b[0] / 2.0) - 64.0, 1)),
    "0F": ("Temperatura do Ar de Admissão (IAT)", "°C", lambda b: b[0] - 40),
    "10": ("Fluxo de Massa de Ar (MAF)", "g/s", lambda b: round(((b[0] * 256) + b[1]) / 100.0, 2)),
    "11": ("Posição da Borboleta (TPS)", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "14": ("Sonda Lambda B1S1 (Tensão / STFT)", "V", lambda b: round(b[0] / 200.0, 3)),
    "15": ("Sonda Lambda B1S2 Pós-Catalisador", "V", lambda b: round(b[0] / 200.0, 3)),
    "1F": ("Tempo de Motor Ligado", "s", lambda b: (b[0] * 256) + b[1]),
    "21": ("Distância Percorrida com Luz MIL Acesa", "km", lambda b: (b[0] * 256) + b[1]),
    "22": ("Pressão de Rail (Relativa ao Vácuo)", "kPa", lambda b: round(((b[0] * 256) + b[1]) * 0.079, 1)),
    "23": ("Pressão de Rail Common Rail / GDI (Alta)", "bar", lambda b: round((((b[0] * 256) + b[1]) * 10.0) / 100.0, 1)),
    "24": ("Sonda Banda Larga B1S1 (Lambda Equiv.)", "λ", lambda b: round(((b[0] * 256) + b[1]) * 2.0 / 65536.0, 3)),
    "2C": ("EGR Comandada", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "2D": ("Erro da EGR", "%", lambda b: round((b[0] - 128) * 100.0 / 128.0, 1)),
    "2E": ("Purga do Canister EVAP Comandada", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "2F": ("Nível do Tanque de Combustível", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "31": ("Distância Desde a Última Limpeza de DTCs", "km", lambda b: (b[0] * 256) + b[1]),
    "33": ("Pressão Barométrica Absoluta", "kPa", lambda b: b[0]),
    "3C": ("Temperatura do Catalisador B1S1", "°C", lambda b: round((((b[0] * 256) + b[1]) / 10.0) - 40.0, 1)),
    "42": ("Tensão Interna da ECU (Módulo de Controle)", "V", lambda b: round(((b[0] * 256) + b[1]) / 1000.0, 2)),
    "43": ("Carga Absoluta do Motor", "%", lambda b: round(((b[0] * 256) + b[1]) * 100.0 / 255.0, 1)),
    "44": ("Relação Equivalente Comandada (AFR/Lambda)", "λ", lambda b: round(((b[0] * 256) + b[1]) * 2.0 / 65536.0, 3)),
    "45": ("Posição Relativa da Borboleta", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "46": ("Temperatura do Ar Ambiente", "°C", lambda b: b[0] - 40),
    "49": ("Pedal do Acelerador Pista D (APP_D)", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "4A": ("Pedal do Acelerador Pista E (APP_E)", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "52": ("Porcentagem de Etanol no Combustível (Flex)", "%", lambda b: round(b[0] * 100.0 / 255.0, 1)),
    "5C": ("Temperatura do Óleo do Motor", "°C", lambda b: b[0] - 40),
    "5E": ("Taxa de Consumo de Combustível", "L/h", lambda b: round(((b[0] * 256) + b[1]) / 20.0, 2)),
}


def extract_hex_bytes_from_elm_lines(raw_resp: str, expected_service_reply: str) -> List[int]:
    """
    Reconstrói payload ISO-TP (Single-Frame ou Multi-Frame) a partir da saída do ELM327/vLinker
    com ATH1 e ATS0 habilitados (ex: 7E806410C1A80... ou 7E81014490201... 7E821...).
    """
    lines = [l.strip().replace(" ", "").upper() for l in raw_resp.splitlines() if l.strip()]
    payload_bytes: List[int] = []

    for line in lines:
        if any(err in line for err in ("NODATA", "ERROR", "UNABLE", "STOPPED", "?", "SEARCHING", "BUSINIT")):
            continue
        # Remove header de 3 hex (ex: 7E8, 7E9, 7EA, 7EB, 7EC) se ATH1 estiver ativo
        if len(line) >= 5 and re.match(r"^7E[8-F][0-9A-F]+$", line):
            data_hex = line[3:]
        else:
            data_hex = line

        if len(data_hex) < 2:
            continue

        pci_type = int(data_hex[0], 16)
        # Single Frame (0x0N)
        if pci_type == 0:
            length = int(data_hex[1], 16)
            frame_hex = data_hex[2 : 2 + length * 2]
            payload_bytes.extend(int(frame_hex[i : i + 2], 16) for i in range(0, len(frame_hex), 2) if i + 2 <= len(frame_hex))
        # First Frame (0x1N LL)
        elif pci_type == 1 and len(data_hex) >= 4:
            frame_hex = data_hex[4:]
            payload_bytes.extend(int(frame_hex[i : i + 2], 16) for i in range(0, len(frame_hex), 2) if i + 2 <= len(frame_hex))
        # Consecutive Frame (0x2N)
        elif pci_type == 2:
            frame_hex = data_hex[2:]
            payload_bytes.extend(int(frame_hex[i : i + 2], 16) for i in range(0, len(frame_hex), 2) if i + 2 <= len(frame_hex))
        else:
            # Caso ATH0 / sem PCI explícito
            payload_bytes.extend(int(data_hex[i : i + 2], 16) for i in range(0, len(data_hex), 2) if i + 2 <= len(data_hex))

    # Procura início do serviço esperado (ex: '410C', '5902', '4902', '62F190')
    exp_bytes = [int(expected_service_reply[i : i + 2], 16) for i in range(0, len(expected_service_reply), 2)]
    for idx in range(len(payload_bytes) - len(exp_bytes) + 1):
        if payload_bytes[idx : idx + len(exp_bytes)] == exp_bytes:
            return payload_bytes[idx + len(exp_bytes) :]
    return []


def decode_dtc_2bytes(b1: int, b2: int) -> str:
    prefix_map = {0: "P", 1: "C", 2: "B", 3: "U"}
    prefix = prefix_map[(b1 >> 6) & 0x03]
    digit1 = (b1 >> 4) & 0x03
    digit2 = b1 & 0x0F
    digit3 = (b2 >> 4) & 0x0F
    digit4 = b2 & 0x0F
    return f"{prefix}{digit1:X}{digit2:X}{digit3:X}{digit4:X}"


def decode_uds_status_mask(mask: int) -> str:
    flags = []
    if mask & 0x01:
        flags.append("🔴 ATIVA AGORA (testFailed)")
    if mask & 0x04:
        flags.append("🟡 PENDENTE (pendingDTC)")
    if mask & 0x08:
        flags.append("🟠 CONFIRMADA (confirmedDTC)")
    if mask & 0x80:
        flags.append("🚨 LUZ MIL ACESA")
    if not (mask & 0x01) and (mask & (0x08 | 0x20)):
        flags.append("⚪ HISTÓRICA / MEMÓRIA PASSADA")
    return " | ".join(flags) if flags else f"Status 0x{mask:02X}"


# ==============================================================================
# ROTINAS DE DIAGNÓSTICO DE CAMPO
# ==============================================================================

def run_vlinker_audit(elm: ELM327Connection) -> None:
    print("\n🔍 [1] AUDITORIA DE HARDWARE DO SCANNER (Vgate vLinker MC+ / ELM327)")
    print("=" * 72)
    report = elm.audit_elm327_chip()
    # Testa comandos exclusivos STN / vLinker (STI, STDI, VT)
    sti = elm.send_raw("STI", timeout=1.0)
    stdi = elm.send_raw("STDI", timeout=1.0)
    vt_ver = elm.send_raw("AT@1", timeout=1.0)

    print(f"• Endereço Conectado : {report['connected_address']}")
    print(f"• Identificação ATI  : {report['declared_version']}")
    print(f"• Descrição Fabric.  : {vt_ver}")
    if "?" not in sti and sti:
        print(f"• Firmware STN/MIC   : {sti} | Hardware: {stdi}")
        print("• Suporte Multi-CAN  : ✅ HS-CAN (Pinos 6/14), MS-CAN (Pinos 3/11) e SW-CAN (Pino 1) suportados!")
    print(f"• Tensão Pino 16 OBD : {report['battery_voltage']}")
    print(f"• Classificação Real : {report['chip_classification']}")
    print(f"• Capacidades Reais  : {report['capabilities_summary']}")
    if report["rejected_commands"]:
        print(f"• Comandos Rejeitados: {', '.join(report['rejected_commands'])}")


def run_vehicle_identification(elm: ELM327Connection) -> None:
    print("\n🚗 [2] IDENTIFICAÇÃO DO VEÍCULO, PROTOCOLO E CHASSI (VIN)")
    print("=" * 72)
    elm.initialize_elm("0")
    # Dispara 0100 para travar no protocolo do carro
    r0100 = elm.send_raw("0100", timeout=4.0)
    dp = elm.send_raw("ATDP", timeout=1.0)
    dpn = elm.send_raw("ATDPN", timeout=1.0)
    rv = elm.send_raw("ATRV", timeout=1.0)

    print(f"• Protocolo Detectado: {dp} (Código {dpn})")
    print(f"• Tensão da Bateria  : {rv}")
    print(f"• Resposta 0100      : {r0100}")

    # Tenta ler VIN via Modo 09 02 e via UDS 22 F1 90
    vin_str = ""
    raw_0902 = elm.send_raw("0902", timeout=3.0)
    b_0902 = extract_hex_bytes_from_elm_lines(raw_0902, "4902")
    if b_0902:
        ascii_chars = [chr(b) for b in b_0902 if 32 <= b <= 126]
        candidate = "".join(ascii_chars).strip()
        m = re.search(r"[A-HJ-NPR-Z0-9]{17}", candidate)
        if m:
            vin_str = m.group(0)

    if not vin_str:
        elm.set_header("7E0")
        raw_uds_vin = elm.send_raw("22F190", timeout=2.5)
        b_uds = extract_hex_bytes_from_elm_lines(raw_uds_vin, "62F190")
        if b_uds:
            candidate = "".join(chr(b) for b in b_uds if 32 <= b <= 126)
            m = re.search(r"[A-HJ-NPR-Z0-9]{17}", candidate)
            if m:
                vin_str = m.group(0)
        elm.set_header("7DF")

    if vin_str:
        print(f"• VIN (Chassi) Lido  : {vin_str}")
        try:
            from app.vin_decoder import decode_vin_Offline_or_Online
            decoded = decode_vin_Offline_or_Online(vin_str)
            print(f"• Decodificação VIN  : {json.dumps(decoded, ensure_ascii=False)}")
        except Exception:
            pass
    else:
        print("• VIN (Chassi) Lido  : Não disponibilizado digitalmente pela ECU (comum em modelos pré-2010 ou Euro 3/4)")


def run_full_dtc_scan(elm: ELM327Connection) -> None:
    print("\n🚨 [3] VARREDURA PROFUNDA DE FALHAS (OBD-II + UDS MULTI-MÓDULO)")
    print("=" * 72)
    elm.initialize_elm("0")
    elm.send_raw("0100", timeout=3.5)

    # 1. Monitor de Prontidão e Luz MIL (01 01)
    r0101 = elm.send_raw("0101", timeout=2.0)
    b0101 = extract_hex_bytes_from_elm_lines(r0101, "4101")
    if len(b0101) >= 4:
        mil_on = bool(b0101[0] & 0x80)
        dtc_count = b0101[0] & 0x7F
        print(f"• Status Luz de Injeção (MIL): {'🚨 ACESA' if mil_on else '✅ APAGADA'} | Contagem OBD: {dtc_count} falha(s)")

    # 2. Modos OBD-II Globais: 03 (Confirmadas), 07 (Pendentes), 0A (Permanentes)
    for mode_cmd, reply_hdr, label in [
        ("03", "43", "Modo 03 (Confirmadas na Injeção/Câmbio)"),
        ("07", "47", "Modo 07 (Pendentes no Ciclo Atual)"),
        ("0A", "4A", "Modo 0A (Permanentes / Histórico Crítico)"),
    ]:
        raw = elm.send_raw(mode_cmd, timeout=3.0)
        b_list = extract_hex_bytes_from_elm_lines(raw, reply_hdr)
        codes = []
        # No CAN ISO 15765-4, o primeiro byte após 0x43/0x47/0x4A é a quantidade de DTCs
        if b_list:
            start_idx = 1 if (len(b_list) % 2 == 1) else 0
            for i in range(start_idx, len(b_list) - 1, 2):
                b1, b2 = b_list[i], b_list[i + 1]
                if b1 == 0 and b2 == 0:
                    continue
                c = decode_dtc_2bytes(b1, b2)
                codes.append(c)
        print(f"\n📌 {label}:")
        if codes:
            for c in codes:
                print(f"   ➔ {c}: {lookup_dtc_description(c)}")
        else:
            print("   ✅ Nenhuma falha encontrada neste modo.")

    # 3. Varredura Física UDS (Serviço 19 02 FF / 19 02 09) por Módulo
    modules = [
        ("7E0", "ECM / Injeção Eletrônica (Motor)"),
        ("7E1", "TCM / Transmissão ou ABS/ESP"),
        ("7E2", "ABS / ESP / Chassi / Inversor"),
        ("7E3", "BCM / Chassi / Airbags"),
        ("7E4", "BCM / Bateria HV / Conforto"),
    ]
    print("\n🔬 Varredura UDS Direta por Módulo (Serviço 0x19 Sub 0x02 Mask 0xFF):")
    for hdr, mod_name in modules:
        elm.set_header(hdr)
        raw_uds = elm.send_raw("1902FF", timeout=2.5)
        b_uds = extract_hex_bytes_from_elm_lines(raw_uds, "5902")
        if len(b_uds) >= 5:
            # b_uds[0] é a status availability mask, seguido de blocos de 4 bytes: [DTC_H, DTC_M, FTB, Status]
            dtc_bytes = b_uds[1:]
            found_uds = []
            for i in range(0, len(dtc_bytes) - 3, 4):
                dh, dm, ftb, st = dtc_bytes[i], dtc_bytes[i + 1], dtc_bytes[i + 2], dtc_bytes[i + 3]
                if dh == 0 and dm == 0:
                    continue
                base_code = decode_dtc_2bytes(dh, dm)
                full_code = f"{base_code}({ftb:02X})"
                st_desc = decode_uds_status_mask(st)
                found_uds.append((full_code, base_code, st_desc))
            print(f"   🏛️ [{hdr}] {mod_name}: {len(found_uds)} falha(s) UDS registrada(s)")
            for fc, bc, sd in found_uds:
                print(f"      • {fc} [{sd}] — {lookup_dtc_description(bc)}")
        else:
            print(f"   🏛️ [{hdr}] {mod_name}: Sem falhas UDS ou módulo silencioso.")
    elm.set_header("7DF")


def run_freeze_frame(elm: ELM327Connection) -> None:
    print("\n❄️ [4] FREEZE FRAME (FOTOGRAFIA DO MOMENTO EXATO DA FALHA - MODO 02)")
    print("=" * 72)
    elm.set_header("7DF")
    # PID 020200 = DTC que gerou o Freeze Frame
    r_dtc = elm.send_raw("020200", timeout=2.0)
    b_dtc = extract_hex_bytes_from_elm_lines(r_dtc, "420200")
    if len(b_dtc) >= 2 and (b_dtc[0] != 0 or b_dtc[1] != 0):
        ff_dtc = decode_dtc_2bytes(b_dtc[0], b_dtc[1])
        print(f"• Falha Causadora do Freeze Frame: {ff_dtc} ({lookup_dtc_description(ff_dtc)})")
    else:
        print("• Nenhum DTC de Freeze Frame ativo armazenado no Modo 02 (ou ECU limpa).")

    ff_pids = ["04", "05", "06", "07", "0B", "0C", "0D", "0E", "0F", "10", "11", "23", "42"]
    for pid in ff_pids:
        raw = elm.send_raw(f"02{pid}00", timeout=1.5)
        b_val = extract_hex_bytes_from_elm_lines(raw, f"42{pid}00")
        if b_val and pid in PID_FORMULAS:
            name, unit, fn = PID_FORMULAS[pid]
            try:
                val = fn(b_val)
                print(f"  • [PID {pid}] {name}: {val} {unit}")
            except Exception:
                pass


def run_live_telemetry(elm: ELM327Connection, profile: str = "all", duration_sec: int = 10) -> None:
    profiles = {
        "mixture": ["0C", "05", "06", "07", "0B", "10", "14", "15", "24"],
        "fuel_rail": ["0C", "04", "0A", "22", "23", "0B", "11", "5E"],
        "thermal_elec": ["0C", "05", "0F", "42", "5C", "3C", "46"],
        "all": ["0C", "04", "05", "06", "07", "0B", "0D", "0E", "0F", "10", "11", "14", "23", "42"],
    }
    pids = profiles.get(profile, profiles["all"])
    print(f"\n📈 [5] CAPTURA DE DADOS AO VIVO (Perfil: {profile.upper()} | Duração: {duration_sec}s)")
    print("=" * 72)

    elm.set_header("7DF")
    atrv = elm.send_raw("ATRV", timeout=1.0)
    print(f"🔋 Tensão na Tomada OBD-II (ATRV): {atrv}\n")

    history: Dict[str, List[float]] = {p: [] for p in pids}
    t_start = time.time()
    sample_idx = 0

    while (time.time() - t_start) < duration_sec:
        sample_idx += 1
        row_Parts = []
        for pid in pids:
            raw = elm.send_raw(f"01{pid}", timeout=1.2)
            b_val = extract_hex_bytes_from_elm_lines(raw, f"41{pid}")
            if b_val and pid in PID_FORMULAS:
                name, unit, fn = PID_FORMULAS[pid]
                try:
                    val = float(fn(b_val))
                    history[pid].append(val)
                    short_name = name.split("(")[-1].replace(")", "") if "(" in name else pid
                    row_Parts.append(f"{short_name}: {val}{unit}")
                except Exception:
                    pass
        if row_Parts:
            print(f"[{sample_idx:02d}] " + " | ".join(row_Parts))
        else:
            print(f"[{sample_idx:02d}] Sem resposta dos PIDs (verifique se a chave de ignição está ligada).")
            break

    print("\n📊 RESUMO ESTATÍSTICO DA CAPTURA (Mín / Méd / Máx):")
    print("-" * 72)
    for pid, vals in history.items():
        if vals:
            name, unit, _ = PID_FORMULAS[pid]
            mn = min(vals)
            mx = max(vals)
            avg = sum(vals) / len(vals)
            print(f"• [01{pid}] {name:<45}: Mín={mn:.2f} | Méd={avg:.2f} | Máx={mx:.2f} {unit}")


def main():
    parser = argparse.ArgumentParser(description="AgentCarDiag — Especialista ELM327 / vLinker MC+")
    parser.add_argument("--scan-bt", action="store_true", help="Escaneia dispositivos Bluetooth próximos (vLinker MC+ / ELM327)")
    parser.add_argument("--pair", type=str, help="Pareia com o MAC Bluetooth informado")
    parser.add_argument("--target", type=str, default="auto", help="MAC Bluetooth, /dev/rfcomm0 ou auto")
    parser.add_argument("--channel", type=int, default=0, help="Canal RFCOMM Bluetooth (0 = auto 1..6)")
    parser.add_argument("--audit", action="store_true", help="Audita o chip do vLinker MC+ / ELM327 e lê tensão")
    parser.add_argument("--identify", action="store_true", help="Identifica protocolo, VIN e ECU do veículo")
    parser.add_argument("--dtcs", action="store_true", help="Varredura completa de códigos de falha (OBD + UDS)")
    parser.add_argument("--freeze-frame", action="store_true", help="Lê Freeze Frame (Modo 02) do momento da falha")
    parser.add_argument("--live", type=str, choices=["mixture", "fuel_rail", "thermal_elec", "all"], help="Captura leituras ao vivo dos sensores")
    parser.add_argument("--duration", type=int, default=8, help="Duração em segundos da captura ao vivo")
    parser.add_argument("--raw", type=str, help="Envia um comando Hex/AT personalizado (ex: '22F190' ou '010C')")
    parser.add_argument("--header", type=str, default="7DF", help="Header CAN para --raw (ex: 7E0, 7E1, 7DF)")

    args = parser.parse_args()

    if args.scan_bt:
        devs = scan_bluetooth_devices(8)
        print("\n=== DISPOSITIVOS BLUETOOTH ENCONTRADOS ===")
        for d in devs:
            tag = "🎯 [CANDIDATO SCANNER]" if d["is_elm_candidate"] == "SIM" else "   [Outro Dispositivo]"
            print(f"{tag} MAC: {d['mac']} | Nome: {d['name']}")
        return

    if args.pair:
        pair_bluetooth_elm(args.pair)
        return

    elm = ELM327Connection(target=args.target, channel=args.channel)
    ok, msg = elm.connect()
    print(f"🔌 Status da Conexão: {msg}")
    if not ok:
        sys.exit(1)

    try:
        if args.audit:
            run_vlinker_audit(elm)
        if args.identify:
            run_vehicle_identification(elm)
        if args.dtcs:
            run_full_dtc_scan(elm)
        if args.freeze_frame:
            run_freeze_frame(elm)
        if args.live:
            run_live_telemetry(elm, profile=args.live, duration_sec=args.duration)
        if args.raw:
            elm.initialize_elm("0")
            if args.header:
                elm.set_header(args.header)
            resp = elm.send_raw(args.raw, timeout=3.0)
            print(f"📤 TX [{args.header}]: {args.raw}\n📥 RX:\n{resp}")
    finally:
        elm.close()


if __name__ == "__main__":
    main()
