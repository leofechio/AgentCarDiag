"""Launch DBScar VII USB/Serial & BLE (`55 AA` binary protocol) helper."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Optional

from bleak import BleakClient
import serial
import serial.tools.list_ports

LAUNCH_VID = 0x03EB
LAUNCH_PID = 0x2404

DBSCAR_BLE_MAC = "DC:0D:30:4E:5D:FE"
DBSCAR_BLE_SERVICE = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
DBSCAR_BLE_NOTIFY = "49535343-1e4d-4bd9-ba61-23c647249616"
DBSCAR_BLE_WRITE = "49535343-8841-43f4-a8d4-ecbe34729bb3"

HOST_TO_VCI_HEADER = b"\x55\xAA\xF0\xF8"
VCI_TO_HOST_HEADER = b"\x55\xAA\xF8\xF0"

# OBD-II pin -> Launch internal IO line ID (from libCOMM_ABSTRACT_LAYER.so SetMultiPinComm)
OBD_PIN_TO_LAUNCH_IO: dict[int, int] = {
    1: 4,
    2: 11,
    3: 5,
    4: 9,
    6: 1,
    7: 2,
    8: 3,
    9: 12,
    10: 6,
    11: 8,
    12: 7,
    13: 10,
    14: 13,
}


def calc_checksum(length_bytes: bytes, counter: int, cmd: bytes, data: bytes) -> int:
    """Compute Launch `packVerify` XOR checksum starting from seed 0x08."""
    xor_val = 0x08
    for byte in length_bytes:
        xor_val ^= byte
    xor_val ^= counter & 0xFF
    for byte in cmd:
        xor_val ^= byte
    for byte in data:
        xor_val ^= byte
    return xor_val & 0xFF


def build_packet(cmd: bytes, data: bytes = b"", counter: int = 0x01) -> bytes:
    """Build a complete Launch `55 AA F0 F8` frame."""
    if len(cmd) != 2:
        raise ValueError("Command word must be exactly 2 bytes.")
    payload_len = 1 + len(cmd) + len(data)  # counter + cmd + data
    length_bytes = payload_len.to_bytes(2, "big")
    checksum = calc_checksum(length_bytes, counter, cmd, data)
    return HOST_TO_VCI_HEADER + length_bytes + bytes([counter & 0xFF]) + cmd + data + bytes([checksum])


def _extract_length_prefixed_strings(payload: bytes) -> list[str]:
    """Parse 2-byte big-endian length-prefixed ASCII strings from response payload."""
    items: list[str] = []
    idx = 0
    while idx + 2 <= len(payload):
        slen = int.from_bytes(payload[idx : idx + 2], "big")
        idx += 2
        if slen == 0 or idx + slen > len(payload):
            break
        raw = payload[idx : idx + slen].rstrip(b"\x00")
        text = raw.decode("ascii", errors="replace")
        if text:
            items.append(text)
        idx += slen
    return items


@dataclass
class DBScarResponse:
    counter: int
    cmd: bytes
    data: bytes
    raw: bytes
    checksum_ok: bool


def parse_packet(raw: bytes) -> Optional[DBScarResponse]:
    """Parse a `55 AA F8 F0` response frame."""
    start = raw.find(VCI_TO_HOST_HEADER)
    if start == -1 or len(raw) < start + 10:
        return None
    frame = raw[start:]
    length_bytes = frame[4:6]
    payload_len = int.from_bytes(length_bytes, "big")
    total_len = 6 + payload_len + 1
    if len(frame) < total_len:
        return None
    counter = frame[6]
    cmd = frame[7:9]
    data = frame[9 : 6 + payload_len]
    rx_checksum = frame[6 + payload_len]
    expected = calc_checksum(length_bytes, counter, cmd, data)
    return DBScarResponse(
        counter=counter,
        cmd=cmd,
        data=data,
        raw=frame[:total_len],
        checksum_ok=(rx_checksum == expected),
    )


def find_dbscar_port() -> Optional[str]:
    """Auto-detect the DBScar VII COM/ttyACM port by USB VID/PID."""
    for port in serial.tools.list_ports.comports():
        if port.vid == LAUNCH_VID and port.pid == LAUNCH_PID:
            return port.device
    return None


class DBScarVII:
    """Serial client for Launch DBScar VII over USB CDC."""

    def __init__(self, port: Optional[str] = None, baudrate: int = 115200, timeout: float = 1.0) -> None:
        self.port_name = port or find_dbscar_port()
        if not self.port_name:
            raise RuntimeError("DBScar VII (VID_03EB&PID_2404) not found on any serial port.")
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._counter = 0

    def __enter__(self) -> "DBScarVII":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        self._ser = serial.Serial(
            port=self.port_name,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        self._ser.dtr = True
        self._ser.rts = True
        time.sleep(0.1)
        self._ser.reset_input_buffer()

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()

    def send_command(self, cmd: bytes, data: bytes = b"", wait_s: float = 0.25) -> Optional[DBScarResponse]:
        if not self._ser or not self._ser.is_open:
            raise RuntimeError("Serial port is not open.")
        self._counter = (self._counter + 1) & 0xFF
        pkt = build_packet(cmd, data, counter=self._counter)
        self._ser.reset_input_buffer()
        self._ser.write(pkt)
        self._ser.flush()
        time.sleep(wait_s)
        waiting = self._ser.in_waiting
        if waiting == 0:
            return None
        raw = self._ser.read(waiting)
        return parse_packet(raw)

    def get_adapter_info(self) -> dict[str, object]:
        """Query command `21 03` (AdapterVerInfo: Chip ID & Serial Number)."""
        resp = self.send_command(b"\x21\x03")
        if not resp:
            raise RuntimeError("No response to 21 03 (get_adapter_info).")
        strings = _extract_length_prefixed_strings(resp.data)
        return {
            "chip_id": strings[0] if len(strings) > 0 else None,
            "serial_number": strings[1] if len(strings) > 1 else None,
            "raw_hex": resp.raw.hex(" ").upper(),
            "checksum_ok": resp.checksum_ok,
        }

    def get_firmware_versions(self) -> dict[str, object]:
        """Query command `21 05` (AdapterVer: Bootloader / Firmware / App / HW versions)."""
        resp = self.send_command(b"\x21\x05")
        if not resp:
            raise RuntimeError("No response to 21 05 (get_firmware_versions).")
        strings = _extract_length_prefixed_strings(resp.data)
        return {
            "versions": strings,
            "raw_hex": resp.raw.hex(" ").upper(),
            "checksum_ok": resp.checksum_ok,
        }

    def send_legacy_cmd(self, payload: bytes, wait_s: float = 0.5) -> Optional[DBScarResponse]:
        """Send a legacy/K-Line command wrapped in `27 01` (DiagPlatformProtocol::SendRecvOldCommand)."""
        return self.send_command(b"\x27\x01", payload, wait_s=wait_s)

    def set_ecu_baudrate(self, baud: int = 10400, voltage_logic: int = 3) -> Optional[DBScarResponse]:
        """Configure VCI ECU baudrate (`60 02 <uint32 BE baud> <logic>` via `27 01`)."""
        payload = b"\x60\x02" + int(baud).to_bytes(4, "big") + bytes([voltage_logic & 0xFF])
        return self.send_legacy_cmd(payload)

    def kline_send_recv(self, data: bytes, flags: int = 0, wait_s: float = 0.6) -> Optional[DBScarResponse]:
        """Send/receive raw K-Line frame (`61 2F <uint16 BE flags> <data>` via `27 01`)."""
        payload = b"\x61\x2F" + (flags & 0xFFFF).to_bytes(2, "big") + data
        return self.send_legacy_cmd(payload, wait_s=wait_s)

    def read_voltage(self) -> Optional[DBScarResponse]:
        """Read OBD-II battery voltage (`40 01` via `27 01`)."""
        return self.send_legacy_cmd(b"\x40\x01")

    def get_box_info(self) -> Optional[DBScarResponse]:
        """Read VCI box info (`60 20` via `27 01`)."""
        return self.send_legacy_cmd(b"\x60\x20")

    def get_dbscar_type(self) -> Optional[DBScarResponse]:
        """Read DBScar hardware type (`60 27` via `27 01`)."""
        return self.send_legacy_cmd(b"\x60\x27")

    def reset_comm(self) -> Optional[DBScarResponse]:
        """Reset active ECU communication channel (`62 1A` via `27 01`)."""
        return self.send_legacy_cmd(b"\x62\x1A")

    def select_multi_io_pins(self, pins: list[int], mode: int = 0) -> Optional[DBScarResponse]:
        """Multiplex OBD-II pins using `OBD_PIN_TO_LAUNCH_IO` (`60 1E` via `27 01`)."""
        mapped = bytes([OBD_PIN_TO_LAUNCH_IO[p] for p in pins])
        payload = b"\x60\x1E" + bytes([mode & 0xFF, len(mapped)]) + mapped
        return self.send_legacy_cmd(payload)


def parse_voltage_mv(resp: Optional[DBScarResponse]) -> Optional[int]:
    """Extract battery voltage in millivolts from a `27 01 40 01` response."""
    if not resp or len(resp.data) < 4:
        return None
    return int.from_bytes(resp.data[-2:], "big")


class DBScarVIIBLE:
    """Async BLE client for Launch DBScar VII using ISSC Transparent UART."""

    def __init__(
        self,
        mac: str = DBSCAR_BLE_MAC,
        notify_uuid: str = DBSCAR_BLE_NOTIFY,
        write_uuid: str = DBSCAR_BLE_WRITE,
    ) -> None:
        self.mac = mac
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid
        self._client: Optional[BleakClient] = None
        self._rx_buf = bytearray()
        self._rx_event = asyncio.Event()
        self._counter = 0

    async def __aenter__(self) -> "DBScarVIIBLE":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        self._rx_buf.extend(data)
        self._rx_event.set()

    async def connect(self) -> None:
        self._client = BleakClient(self.mac, timeout=15.0)
        await self._client.connect()
        await self._client.start_notify(self.notify_uuid, self._on_notify)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(self.notify_uuid)
            except Exception:
                pass
            await self._client.disconnect()

    async def send_command(
        self, cmd: bytes, data: bytes = b"", timeout_s: float = 2.0
    ) -> Optional[DBScarResponse]:
        if not self._client or not self._client.is_connected:
            raise RuntimeError("BLE client is not connected.")
        self._counter = (self._counter + 1) & 0xFF
        pkt = build_packet(cmd, data, counter=self._counter)
        self._rx_buf.clear()
        self._rx_event.clear()
        await self._client.write_gatt_char(self.write_uuid, pkt, response=False)
        try:
            await asyncio.wait_for(self._rx_event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None
        await asyncio.sleep(0.12)
        return parse_packet(bytes(self._rx_buf))

    async def get_adapter_info(self) -> dict[str, object]:
        resp = await self.send_command(b"\x21\x03")
        if not resp:
            raise RuntimeError("No BLE response to 21 03.")
        strings = _extract_length_prefixed_strings(resp.data)
        return {
            "chip_id": strings[0] if len(strings) > 0 else None,
            "serial_number": strings[1] if len(strings) > 1 else None,
            "checksum_ok": resp.checksum_ok,
        }

    async def get_firmware_versions(self) -> dict[str, object]:
        resp = await self.send_command(b"\x21\x05")
        if not resp:
            raise RuntimeError("No BLE response to 21 05.")
        return {"versions": _extract_length_prefixed_strings(resp.data), "checksum_ok": resp.checksum_ok}

    async def read_voltage_mv(self) -> Optional[int]:
        resp = await self.send_command(b"\x27\x01", b"\x40\x01")
        return parse_voltage_mv(resp)
