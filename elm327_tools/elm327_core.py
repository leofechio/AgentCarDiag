#!/usr/bin/env python3
"""
ELM327 Core Transport & Protocol Engine — AgentCarDiag
Suporta:
  1. Bluetooth Clássico (RFCOMM Socket direto via kernel Linux - sem precisar de root/rfcomm bind)
  2. Bluetooth Low Energy (BLE 4.0 via Bleak)
  3. Porta Serial (/dev/rfcomm*, /dev/ttyUSB*, /dev/ttyACM*)
  4. Wi-Fi TCP (ex: 192.168.0.10:35000)

Inclui auditoria sincera de chip (PIC18F25K80 v1.5 / STN vs Clones v2.1 capados)
e suporte completo a OBD-II (SAE J1979) e UDS (ISO 14229 / ISO-TP 15765-2).
"""

import asyncio
import glob
import re
import socket
import time
from typing import Dict, List, Optional, Tuple

import serial


class ELM327Connection:
    def __init__(
        self,
        target: str = "auto",
        channel: int = 0,
        baudrate: int = 38400,
        timeout: float = 3.0,
    ):
        """
        target:
          - 'auto': tenta portas seriais (/dev/rfcomm*, /dev/ttyUSB*) ou Bluetooth pareado
          - MAC Bluetooth: ex '00:1D:A5:68:98:8B' ou 'AA:BB:CC:11:22:33'
          - Caminho Serial: ex '/dev/rfcomm0', '/dev/ttyUSB0'
          - IP:Porta: ex '192.168.0.10:35000'
        """
        self.target = target
        self.channel = channel
        self.baudrate = baudrate
        self.timeout = timeout

        self.conn_type: Optional[str] = None  # 'rfcomm_socket', 'serial', 'tcp'
        self.sock: Optional[socket.socket] = None
        self.ser: Optional[serial.Serial] = None
        self.connected_address: str = ""
        self.current_header: str = "7DF"

    def connect(self) -> Tuple[bool, str]:
        target = self.target.strip()

        # 1. Caso seja MAC Bluetooth (XX:XX:XX:XX:XX:XX)
        if re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", target):
            return self._connect_bt_rfcomm(target, self.channel)

        # 2. Caso seja IP:Porta (Wi-Fi ELM327)
        if ":" in target and not target.startswith("/"):
            host, port_str = target.split(":", 1)
            return self._connect_tcp(host, int(port_str))

        # 3. Caso seja porta serial explícita
        if target.startswith("/dev/"):
            return self._connect_serial(target, self.baudrate)

        # 4. Modo AUTO: procura /dev/rfcomm*, /dev/ttyUSB*, /dev/ttyACM*
        for pattern in ["/dev/rfcomm*", "/dev/ttyUSB*", "/dev/ttyACM*"]:
            for dev in sorted(glob.glob(pattern)):
                ok, msg = self._connect_serial(dev, self.baudrate)
                if ok:
                    return True, msg

        return False, (
            "Nenhum adaptador ELM327 encontrado automaticamente em /dev/rfcomm* ou /dev/ttyUSB*. "
            "Use --scan-bt para descobrir o MAC Bluetooth do ELM327 e conecte via --mac XX:XX:XX:XX:XX:XX."
        )

    def _connect_bt_rfcomm(self, mac: str, preferred_channel: int = 0) -> Tuple[bool, str]:
        channels_to_try = [preferred_channel] if preferred_channel > 0 else [1, 2, 3, 4, 5, 6]
        last_err = ""
        for ch in channels_to_try:
            try:
                sock = socket.socket(
                    socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
                )
                sock.settimeout(self.timeout)
                sock.connect((mac, ch))
                self.sock = sock
                self.conn_type = "rfcomm_socket"
                self.connected_address = f"bt://{mac}:ch{ch}"
                return True, f"Conectado via Bluetooth RFCOMM direto em {mac} (Canal {ch})"
            except Exception as e:
                last_err = str(e)
                try:
                    sock.close()
                except Exception:
                    pass
        return False, f"Falha ao conectar via Bluetooth RFCOMM em {mac}: {last_err}"

    def _connect_serial(self, port: str, baudrate: int) -> Tuple[bool, str]:
        bauds = [baudrate, 38400, 115200, 9600, 500000]
        seen = set()
        bauds = [b for b in bauds if not (b in seen or seen.add(b))]

        last_err = ""
        for b in bauds:
            try:
                ser = serial.Serial(port, baudrate=b, timeout=self.timeout)
                self.ser = ser
                self.conn_type = "serial"
                self.connected_address = f"{port}@{b}"
                resp = self.send_raw("ATI", timeout=1.5)
                if "ELM" in resp.upper() or "OBD" in resp.upper() or ">" in resp or "OK" in resp.upper():
                    return True, f"Conectado via Serial em {port} ({b} bps) -> {resp.strip()}"
                # Se abriu mas não respondeu ATI nessa baud, tenta próxima se houver
                ser.close()
            except Exception as e:
                last_err = str(e)
        return False, f"Falha na porta serial {port}: {last_err}"

    def _connect_tcp(self, host: str, port: int) -> Tuple[bool, str]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((host, port))
            self.sock = sock
            self.conn_type = "tcp"
            self.connected_address = f"tcp://{host}:{port}"
            return True, f"Conectado via TCP Wi-Fi em {host}:{port}"
        except Exception as e:
            return False, f"Falha TCP {host}:{port}: {e}"

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def send_raw(self, cmd: str, timeout: Optional[float] = None) -> str:
        """Envia um comando AT ou Hex para o ELM327 e aguarda até o prompt '>'."""
        wait = timeout if timeout is not None else self.timeout
        payload = (cmd.strip() + "\r").encode("ascii", errors="ignore")

        if self.conn_type in ("rfcomm_socket", "tcp") and self.sock:
            self.sock.settimeout(wait)
            # Limpa buffer pendente rápido
            self.sock.setblocking(False)
            try:
                while self.sock.recv(1024):
                    pass
            except Exception:
                pass
            self.sock.settimeout(wait)
            self.sock.sendall(payload)

            buf = bytearray()
            t0 = time.time()
            while (time.time() - t0) < wait:
                try:
                    chunk = self.sock.recv(512)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    if b">" in buf:
                        break
                except socket.timeout:
                    break
                except Exception:
                    break
            return self._clean_response(buf.decode("ascii", errors="ignore"), cmd)

        elif self.conn_type == "serial" and self.ser:
            self.ser.timeout = wait
            self.ser.reset_input_buffer()
            self.ser.write(payload)
            self.ser.flush()

            buf = bytearray()
            t0 = time.time()
            while (time.time() - t0) < wait:
                chunk = self.ser.read(self.ser.in_waiting or 1)
                if chunk:
                    buf.extend(chunk)
                    if b">" in buf:
                        break
            return self._clean_response(buf.decode("ascii", errors="ignore"), cmd)

        return "ERROR: NOT CONNECTED"

    @staticmethod
    def _clean_response(raw: str, sent_cmd: str) -> str:
        text = raw.replace("\r", "\n").replace(">", "")
        lines = []
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            if s.upper() == sent_cmd.strip().upper():
                continue
            lines.append(s)
        return "\n".join(lines)

    def initialize_elm(self, protocol: str = "0") -> Dict[str, str]:
        """
        Inicializa o ELM327 para diagnóstico profissional:
        - ATZ (Reset)
        - ATE0 (Echo Off)
        - ATL0 (Linefeeds Off)
        - ATS0 (Spaces Off para parsing ou ATS1 conforme necessidade)
        - ATH1 (Headers On para identificar qual ECU respondeu: 7E8, 7E9, 7EA, 7EB, 7EC)
        - ATAL (Allow Long messages)
        - ATSP{protocol} (0 = Auto)
        """
        info = {}
        info["ATZ"] = self.send_raw("ATZ", timeout=2.5)
        time.sleep(0.3)
        info["ATE0"] = self.send_raw("ATE0", timeout=1.0)
        info["ATL0"] = self.send_raw("ATL0", timeout=1.0)
        info["ATS0"] = self.send_raw("ATS0", timeout=1.0)
        info["ATH1"] = self.send_raw("ATH1", timeout=1.0)
        info["ATAL"] = self.send_raw("ATAL", timeout=1.0)
        info["ATI"] = self.send_raw("ATI", timeout=1.0)
        info["AT@1"] = self.send_raw("AT@1", timeout=1.0)
        info["ATRV"] = self.send_raw("ATRV", timeout=1.0)
        info["ATSP"] = self.send_raw(f"ATSP{protocol}", timeout=1.5)
        return info

    def audit_elm327_chip(self) -> Dict[str, object]:
        """
        Testa sinceramente se o ELM327 é um chip completo (PIC18F25K80 v1.4/v1.5 / STN / vLinker)
        ou um clone chinês v2.1 restrito que rejeita comandos UDS / Flow Control / K-Line.
        """
        init_data = self.initialize_elm("0")
        test_cmds = {
            "ATI (Versão Declarada)": init_data.get("ATI", ""),
            "AT@1 (Descrição do Fabricante)": init_data.get("AT@1", ""),
            "ATRV (Tensão da Bateria pino 16)": init_data.get("ATRV", ""),
            "ATH1 (Exibir Cabeçalhos CAN)": init_data.get("ATH1", ""),
            "ATAL (Pacotes Longos >7 bytes)": init_data.get("ATAL", ""),
            "ATSH 7E0 (Troca de Header Físico ECU)": self.send_raw("ATSH7E0", timeout=1.0),
            "ATCRA 7E8 (Filtro de Recepção Física)": self.send_raw("ATCRA7E8", timeout=1.0),
            "ATFCSH 7E0 (Custom Flow Control UDS)": self.send_raw("ATFCSH7E0", timeout=1.0),
            "ATFC SD 300000 (Dados Flow Control)": self.send_raw("ATFCSD300000", timeout=1.0),
            "ATFC SM 1 (Modo Flow Control)": self.send_raw("ATFCSM1", timeout=1.0),
            "ATKW0 (Suporte a Linha K / KWP2000)": self.send_raw("ATKW0", timeout=1.0),
            "ATAR (Auto Receive Restore)": self.send_raw("ATAR", timeout=1.0),
            "ATSH 7DF (Restore Broadcast OBD2)": self.send_raw("ATSH7DF", timeout=1.0),
        }

        failed_cmds = [k for k, v in test_cmds.items() if "?" in str(v)]
        version_str = init_data.get("ATI", "").upper()

        if len(failed_cmds) == 0:
            quality = "EXCELENTE (Chip Completo v1.4/v1.5 PIC18F25K80 ou STN)"
            capabilities = (
                "Suporta OBD-II padrão (Motor) + UDS Avançado (ISO 14229 Multi-Frame) + "
                "Endereçamento físico de ABS (7E1), Câmbio (7E1/7E2), BCM/Chassi (7E3/7E4) e Linha K (pino 7)."
            )
        elif "ATFCSH 7E0 (Custom Flow Control UDS)" in failed_cmds and "ATSH 7E0 (Troca de Header Físico ECU)" not in failed_cmds:
            quality = "INTERMEDIÁRIO (Clone parcial)"
            capabilities = (
                "Suporta OBD-II padrão e comandos diretos simples (Single-Frame), mas pode falhar em "
                "respostas longas Multi-Frame UDS (19 02 FF com muitas falhas) ou Linha K antiga."
            )
        else:
            quality = "LIMITADO (Clone Chinês v2.1 Restrito)"
            capabilities = (
                "Atende bem OBD-II Padrão (Injeção/Motor: Modo 01 sensores ao vivo, Modo 02 Freeze Frame, "
                "Modo 03/07/0A leitura de falhas de motor, Modo 04 apagar falhas), porém bloqueia UDS avançado "
                "de outros módulos (ABS/Airbag) e carros antigos K-Line."
            )

        return {
            "connected_address": self.connected_address,
            "declared_version": version_str,
            "battery_voltage": init_data.get("ATRV", "N/A"),
            "chip_classification": quality,
            "capabilities_summary": capabilities,
            "command_matrix": test_cmds,
            "rejected_commands": failed_cmds,
        }

    def set_header(self, header_hex: str):
        clean_h = header_hex.replace("0x", "").replace(" ", "").upper()
        if clean_h == self.current_header:
            return
        self.send_raw(f"ATSH{clean_h}", timeout=1.0)
        # Se for endereço físico 7E0..7E7, configura Flow Control correspondente
        if len(clean_h) == 3 and clean_h.startswith("7E") and clean_h != "7DF":
            try:
                tx_id = int(clean_h, 16)
                rx_id = tx_id + 8
                self.send_raw(f"ATCRA{rx_id:03X}", timeout=1.0)
                self.send_raw(f"ATFCSH{clean_h}", timeout=1.0)
                self.send_raw("ATFCSD300000", timeout=1.0)
                self.send_raw("ATFCSM1", timeout=1.0)
            except Exception:
                pass
        elif clean_h == "7DF":
            self.send_raw("ATAR", timeout=1.0)
        self.current_header = clean_h
