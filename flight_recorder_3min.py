#!/usr/bin/env python3
"""
flight_recorder_3min.py — Gravador de Caixa-Preta em Movimento (Stand-by Trigger + SQLite + JSONL)
Projeto AgentCarDiag

Funcionalidades:
  - Modo Stand-by Automático: aguarda o motor dar a partida (RPM > 100) antes de iniciar o cronômetro.
  - Parada Graciosa: encerra imediatamente se o arquivo 'stop_rec.flag' for criado ou ao atingir a duração.
  - Persistência Dupla: grava cada amostra com flush=True em arquivo .jsonl e na tabela obd_metrics do cardiag.db.
  - Suporta perfis cirúrgicos de 5 a 8 PIDs (Turbo/Diesel, Mistura/Rampa Estática P0171, GDI Rail, Transmissão DSG/PDK).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from vlinker_diag import VLinkerBLE, parse_kwp_or_can_pid_bytes

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "server" / "data" / "cardiag.db"
STOP_FLAG = BASE_DIR / "stop_rec.flag"


def decode_pid(pid: str, b: List[int]) -> Optional[float]:
    if not b:
        return None
    p = pid.upper()
    if p == "010C" and len(b) >= 2:
        return round((b[0] * 256 + b[1]) / 4.0, 1)
    if p == "010D":
        return float(b[0])
    if p == "0104":
        return round(b[0] * 100.0 / 255.0, 1)
    if p in ("0105", "010F", "0146", "015C"):
        return float(b[0] - 40)
    if p in ("0106", "0107", "0108", "0109"):
        return round((b[0] - 128) * 100.0 / 128.0, 2)
    if p in ("010B", "0133", "0170"):
        return float(b[0])
    if p == "010E":
        return round((b[0] / 2.0) - 64.0, 1)
    if p == "0110" and len(b) >= 2:
        return round((b[0] * 256 + b[1]) / 100.0, 2)
    if p in ("0111", "0149", "014A"):
        return round(b[0] * 100.0 / 255.0, 1)
    if p == "0123" and len(b) >= 2:
        # Pressão Rail em bar ((A*256+B)*10 kPa / 100 = bar)
        return round(((b[0] * 256 + b[1]) * 10.0) / 100.0, 1)
    if p in ("0124", "0134", "0144") and len(b) >= 2:
        return round(((b[0] * 256 + b[1]) * 2.0) / 65536.0, 4)
    if p == "0142" and len(b) >= 2:
        return round((b[0] * 256 + b[1]) / 1000.0, 2)
    return float(b[0])


PROFILES: Dict[str, List[str]] = {
    "turbo_diesel": ["010C", "010D", "010B", "0133", "0110", "0123", "0149", "0105"],
    "fuel_trim_ramp": ["010C", "0110", "0106", "0107", "0134", "0104", "0105", "010E"],
    "gdi_rail": ["010C", "0123", "0106", "0107", "010B", "0111", "0149", "0105"],
}


async def record_flight(
    profile: str = "turbo_diesel",
    duration_s: int = 180,
    output_jsonl: str = "flight_log.jsonl",
    protocol: str = "6",
    wait_start: bool = True,
) -> None:
    pids = PROFILES.get(profile, PROFILES["turbo_diesel"])
    out_path = BASE_DIR / output_jsonl
    if STOP_FLAG.exists():
        STOP_FLAG.unlink()

    conn: Optional[sqlite3.Connection] = None
    session_id = "flight_session"
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            row = conn.execute("SELECT id FROM sessions WHERE is_active = 1 LIMIT 1").fetchone()
            if row:
                session_id = row[0]
        except Exception:
            conn = None

    async with VLinkerBLE(protocol=protocol) as vl:
        if protocol in ("0", "3", "4", "5"):
            ok, msg = await vl.ensure_kwp_init()
            print(f"🔌 K-Line Status: {msg}")
        else:
            await vl.set_can_target("7E0", "7E8")

        if wait_start:
            print("⏳ [STAND-BY] Aguardando partida do motor (RPM > 100)...")
            while not STOP_FLAG.exists():
                raw_rpm = await vl.cmd("010C", timeout=2.5)
                b_rpm = parse_kwp_or_can_pid_bytes(raw_rpm, "410C")
                rpm_val = decode_pid("010C", b_rpm) or 0.0
                if rpm_val > 100:
                    print(f"🚀 Motor em funcionamento ({rpm_val} RPM)! Iniciando gravação de {duration_s}s...")
                    break
                await asyncio.sleep(0.5)

        t0 = time.time()
        sample_no = 0
        with open(out_path, "a", encoding="utf-8") as jf:
            while (time.time() - t0) < duration_s and not STOP_FLAG.exists():
                sample_no += 1
                now_iso = datetime.now(timezone.utc).isoformat()
                elapsed = round(time.time() - t0, 2)
                sample: Dict[str, object] = {
                    "sample": sample_no,
                    "timestamp": now_iso,
                    "elapsed_s": elapsed,
                }
                for pid in pids:
                    raw = await vl.cmd(pid, timeout=2.0)
                    expected = "41" + pid[2:]
                    b_data = parse_kwp_or_can_pid_bytes(raw, expected)
                    val = decode_pid(pid, b_data)
                    sample[pid] = val
                    if conn and val is not None:
                        try:
                            conn.execute(
                                "INSERT INTO obd_metrics (session_id, timestamp, metric_name, metric_value, raw_response) VALUES (?, ?, ?, ?, ?)",
                                (session_id, now_iso, pid, float(val), raw),
                            )
                        except Exception:
                            pass

                # Cálculos derivados automáticos (Boost Relativo e Relação RPM/km/h)
                if sample.get("010B") is not None and sample.get("0133") is not None:
                    sample["boost_rel_bar"] = round((float(sample["010B"]) - float(sample["0133"])) / 100.0, 2)
                if sample.get("010C") and sample.get("010D") and float(sample["010D"]) > 1.0:
                    sample["rpm_per_kmh"] = round(float(sample["010C"]) / float(sample["010D"]), 2)

                if conn:
                    conn.commit()
                jf.write(json.dumps(sample, ensure_ascii=False) + "\n")
                jf.flush()
                print(f"[#{sample_no:04d} | {elapsed:6.1f}s] " + " | ".join(f"{k}={v}" for k, v in sample.items() if k not in ("sample", "timestamp", "elapsed_s")))

    if conn:
        conn.close()
    print(f"✅ Gravação concluída ({sample_no} amostras salvas em {out_path}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gravador de Caixa-Preta AgentCarDiag")
    parser.add_argument("--profile", choices=list(PROFILES.keys()), default="turbo_diesel")
    parser.add_argument("--duration", type=int, default=180, help="Duração em segundos (default: 180)")
    parser.add_argument("--out", default="flight_log.jsonl", help="Arquivo JSONL de saída")
    parser.add_argument("--proto", default="6", help="Protocolo ATSP (6=CAN, 0=Auto/K-Line)")
    parser.add_argument("--no-wait", action="store_true", help="Inicia imediatamente sem aguardar RPM > 100")
    args = parser.parse_args()
    asyncio.run(
        record_flight(
            profile=args.profile,
            duration_s=args.duration,
            output_jsonl=args.out,
            protocol=args.proto,
            wait_start=not args.no_wait,
        )
    )


if __name__ == "__main__":
    main()
