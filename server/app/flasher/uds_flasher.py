"""
Gerador de Sequências UDS Flasher (ISO 14229 / ISO 15765-2).
Responsável por montar o pacote de dados fatiado em blocos para gravação segura.
"""
from typing import List, Dict, Any
import hashlib

class UdsFlasherBuilder:
    def __init__(self, target_ecu_header: str = "7E0", rx_header: str = "7E8"):
        self.tx_header = target_ecu_header
        self.rx_header = rx_header

    def build_programming_session(self) -> Dict[str, Any]:
        """Comando 0x10 02: Solicita entrada em Sessão de Programação."""
        return {
            "step": "ENTER_PROGRAMMING_SESSION",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": "02 10 02",
            "desc": "Service 0x10 02 - DiagnosticSessionControl (Programming Session)"
        }

    def build_extended_session(self) -> Dict[str, Any]:
        """Comando 0x10 03: Sessão Estendida."""
        return {
            "step": "ENTER_EXTENDED_SESSION",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": "02 10 03",
            "desc": "Service 0x10 03 - DiagnosticSessionControl (Extended Session)"
        }

    def build_request_seed(self, security_level: int = 1) -> Dict[str, Any]:
        """Comando 0x27 01 (ou nível ímpar): Solicita Seed da ECU."""
        return {
            "step": "REQUEST_SEED",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": f"02 27 {security_level:02X}",
            "desc": f"Service 0x27 {security_level:02X} - SecurityAccess Request Seed"
        }

    def build_send_key(self, security_level: int, key_hex: str) -> Dict[str, Any]:
        """Comando 0x27 02 (ou nível par): Envia Chave calculada."""
        clean_key = key_hex.replace(" ", "").upper()
        key_bytes = [clean_key[i:i+2] for i in range(0, len(clean_key), 2)]
        length = len(key_bytes) + 2
        payload = f"{length:02X} 27 {security_level + 1:02X} " + " ".join(key_bytes)
        return {
            "step": "SEND_KEY",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": payload,
            "desc": f"Service 0x27 {security_level+1:02X} - SecurityAccess Send Key"
        }

    def build_request_download(self, start_address: int, total_size: int) -> Dict[str, Any]:
        """
        Comando 0x34: RequestDownload.
        addr_len: 4 bytes, size_len: 4 bytes -> format_byte = 0x44
        """
        addr_hex = f"{start_address:08X}"
        size_hex = f"{total_size:08X}"
        addr_parts = " ".join([addr_hex[i:i+2] for i in range(0, 8, 2)])
        size_parts = " ".join([size_hex[i:i+2] for i in range(0, 8, 2)])
        
        # 0x00 (sem compressão/criptografia) + 0x44 (4 bytes addr + 4 bytes len)
        payload = f"0A 34 00 44 {addr_parts} {size_parts}"
        return {
            "step": "REQUEST_DOWNLOAD",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": payload,
            "desc": f"Service 0x34 - RequestDownload (Addr: 0x{start_address:08X}, Size: {total_size} bytes)"
        }

    def slice_into_transfer_blocks(self, binary_data: bytes, block_size: int = 1024) -> List[Dict[str, Any]]:
        """
        Fatia o arquivo binário em blocos sequenciais UDS 0x36 (TransferData).
        block_sequence inicia em 1 e rotaciona até 255 (0xFF).
        """
        blocks = []
        total_len = len(binary_data)
        seq = 1
        
        for offset in range(0, total_len, block_size):
            chunk = binary_data[offset:offset + block_size]
            chunk_hex = chunk.hex().upper()
            chunk_parts = " ".join([chunk_hex[i:i+2] for i in range(0, len(chunk_hex), 2)])
            
            # Payload ISO-TP multi-frame (comprimento calculado no driver ISO-TP do ESP32)
            payload = f"36 {seq:02X} {chunk_parts}"
            
            blocks.append({
                "block_number": seq,
                "offset": offset,
                "chunk_size": len(chunk),
                "header": self.tx_header,
                "expected_rx": self.rx_header,
                "payload": payload,
                "desc": f"Service 0x36 - TransferData Block #{seq} ({len(chunk)} bytes)"
            })
            
            seq = (seq + 1) & 0xFF
            if seq == 0:
                seq = 1  # No padrão ISO 14229, volta para 0 ou 1 dependendo da montadora
                
        return blocks

    def build_transfer_exit(self) -> Dict[str, Any]:
        """Comando 0x37: RequestTransferExit."""
        return {
            "step": "REQUEST_TRANSFER_EXIT",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": "01 37",
            "desc": "Service 0x37 - RequestTransferExit (Finalização da transferência de dados)"
        }

    def build_checksum_routine(self, checksum_crc32: int) -> Dict[str, Any]:
        """Comando 0x31 01: RoutineControl (Verificação de Checksum/Integridade)."""
        crc_hex = f"{checksum_crc32:08X}"
        crc_parts = " ".join([crc_hex[i:i+2] for i in range(0, 8, 2)])
        return {
            "step": "CHECK_INTEGRITY",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": f"06 31 01 02 02 {crc_parts}",
            "desc": f"Service 0x31 01 02 02 - RoutineControl CheckMemory (CRC32: 0x{checksum_crc32:08X})"
        }

    def build_ecu_reset(self) -> Dict[str, Any]:
        """Comando 0x11 01: Hard Reset da ECU."""
        return {
            "step": "ECU_RESET",
            "header": self.tx_header,
            "expected_rx": self.rx_header,
            "payload": "02 11 01",
            "desc": "Service 0x11 01 - ECUReset (Reinicializa módulo com a nova calibração)"
        }
