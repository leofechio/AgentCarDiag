#!/usr/bin/env python3
"""
Bluetooth Scanner & Auto-Pairer para Adaptadores ELM327 (Classic SPP & BLE 4.0)
"""

import re
import subprocess
import sys
import time
from typing import Dict, List


ELM_KEYWORDS = [
    "OBD", "ELM", "V-LINK", "VLINK", "KONNWEI", "VGATE",
    "ICAR", "SCAN", "CAR", "CHX", "CBT", "VPECKER", "VIECCAR", "IOS-VLINK"
]


def ensure_bluetooth_ready() -> None:
    """Desbloqueia rfkill e liga o controlador Bluetooth hci0."""
    subprocess.run(["rfkill", "unblock", "bluetooth"], check=False)
    time.sleep(0.5)
    subprocess.run(["bluetoothctl", "power", "on"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["bluetoothctl", "agent", "on"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def scan_bluetooth_devices(scan_seconds: int = 8) -> List[Dict[str, str]]:
    """
    Executa varredura Bluetooth (Clássico + BLE) via bluetoothctl e retorna
    todos os dispositivos encontrados, destacando os candidatos a ELM327.
    """
    ensure_bluetooth_ready()
    print(f"📡 Escaneando dispositivos Bluetooth por {scan_seconds} segundos (mantenha o ELM327 alimentado na tomada OBD2)...")

    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        proc.stdin.write("power on\n")
        proc.stdin.write("scan on\n")
        proc.stdin.flush()
        time.sleep(scan_seconds)
        proc.stdin.write("scan off\n")
        proc.stdin.write("devices\n")
        proc.stdin.write("quit\n")
        proc.stdin.flush()
        out, _ = proc.communicate(timeout=5)
    except Exception:
        proc.kill()
        out = ""

    # Também consulta bluetoothctl devices diretamente
    res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True)
    combined = (out or "") + "\n" + (res.stdout or "")

    devices: Dict[str, str] = {}
    for line in combined.splitlines():
        m = re.search(r"Device\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s+(.+)", line)
        if m:
            mac = m.group(1).upper()
            name = m.group(2).strip()
            # Ignora nomes que são apenas o próprio MAC repetido se já tivermos um nome melhor
            if mac not in devices or re.match(r"^[0-9A-Fa-f:-]+$", devices[mac]):
                devices[mac] = name

    results = []
    for mac, name in devices.items():
        upper_name = name.upper()
        is_elm_candidate = any(k in upper_name for k in ELM_KEYWORDS) or mac.startswith(("00:1D:A5", "AA:BB:CC", "00:0D:18", "66:35:56", "88:18:56"))
        results.append({
            "mac": mac,
            "name": name,
            "is_elm_candidate": "SIM" if is_elm_candidate else "NAO",
        })

    # Ordena colocando candidatos a ELM327 primeiro
    results.sort(key=lambda x: (0 if x["is_elm_candidate"] == "SIM" else 1, x["name"]))
    return results


def pair_bluetooth_elm(mac: str, pin: str = "1234") -> bool:
    """
    Tenta parear e confiar no endereço MAC do ELM327 informando o PIN clássico (1234 ou 0000).
    """
    ensure_bluetooth_ready()
    print(f"🔗 Tentando parear com {mac} (PIN padrão: {pin})...")

    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        cmds = [
            "power on\n",
            "agent on\n",
            "default-agent\n",
            f"trust {mac}\n",
            f"pair {mac}\n",
        ]
        for c in cmds:
            proc.stdin.write(c)
            proc.stdin.flush()
            time.sleep(0.6)

        # Envia PIN caso o bluetoothctl solicite Passkey / PIN code
        time.sleep(2.0)
        proc.stdin.write(f"{pin}\n")
        proc.stdin.flush()
        time.sleep(2.0)
        proc.stdin.write("yes\n")
        proc.stdin.flush()
        time.sleep(1.0)
        proc.stdin.write("quit\n")
        proc.stdin.flush()
        out, _ = proc.communicate(timeout=6)
    except Exception:
        proc.kill()
        out = ""

    info = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True).stdout
    if "Paired: yes" in info:
        print(f"✅ Dispositivo {mac} pareado com sucesso!")
        return True
    print(f"⚠️ Status do pareamento para {mac}:\n{info or out}")
    return False


if __name__ == "__main__":
    scan_time = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    found = scan_bluetooth_devices(scan_time)
    print("\n=== DISPOSITIVOS BLUETOOTH ENCONTRADOS ===")
    if not found:
        print("Nenhum dispositivo encontrado.")
    for d in found:
        tag = "🎯 [CANDIDATO ELM327]" if d["is_elm_candidate"] == "SIM" else "   [Outro Dispositivo]"
        print(f"{tag} MAC: {d['mac']} | Nome: {d['name']}")
