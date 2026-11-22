"""CLI for inspecting and testing Launch DBScar VII over USB and Bluetooth LE."""

from __future__ import annotations

import argparse
import asyncio
import sys

from dbscar7 import DBSCAR_BLE_MAC, DBScarVII, DBScarVIIBLE, find_dbscar_port


async def run_ble(mac: str) -> int:
    async with DBScarVIIBLE(mac=mac) as vci:
        info = await vci.get_adapter_info()
        fw = await vci.get_firmware_versions()
        mv = await vci.read_voltage_mv()
        print(f"Connected via BLE to DBScar VII ({mac})")
        print(f"Serial Number : {info['serial_number']}")
        print(f"Chip ID       : {info['chip_id']}")
        print(f"Versions      : {', '.join(fw['versions'])}")
        print(f"OBD Voltage   : {mv / 1000:.2f} V ({mv} mV)" if mv is not None else "OBD Voltage   : N/A")
        print(f"Checksums OK  : {info['checksum_ok'] and fw['checksum_ok']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch DBScar VII USB/BLE Diagnostic Tool")
    parser.add_argument("--ble", action="store_true", help="Connect via Bluetooth LE (no pairing needed)")
    parser.add_argument("--mac", default=DBSCAR_BLE_MAC, help=f"BLE MAC address (default: {DBSCAR_BLE_MAC})")
    parser.add_argument("--port", help="Serial port (default: auto-detect VID_03EB&PID_2404)")
    parser.add_argument("--raw", help="Send custom hex command+data (e.g. '2103' or '2105')")
    parser.add_argument("--baud", type=int, help="Set ECU K-Line baudrate (e.g. 10400, 9600)")
    parser.add_argument("--kline", help="Send raw K-Line hex payload wrapped in 27 01 / 61 2F")
    args = parser.parse_args()

    if args.ble:
        return asyncio.run(run_ble(args.mac))

    port = args.port or find_dbscar_port()
    if not port:
        print("DBScar VII not detected. Check USB connection.")
        return 1

    with DBScarVII(port=port) as vci:
        print(f"Connected to DBScar VII on {vci.port_name} @ {vci.baudrate} bps")

        if args.baud:
            resp = vci.set_ecu_baudrate(args.baud)
            print(f"Set baud {args.baud}:", resp.raw.hex(" ").upper() if resp else "No response")
            if not args.kline:
                return 0 if resp else 1

        if args.kline:
            kdata = bytes.fromhex(args.kline.replace(" ", ""))
            resp = vci.kline_send_recv(kdata)
            print("K-Line RX:", resp.raw.hex(" ").upper() if resp else "No response")
            return 0 if resp else 1

        if args.raw:
            raw_bytes = bytes.fromhex(args.raw.replace(" ", ""))
            if len(raw_bytes) < 2:
                print("--raw requires at least 2 command bytes (e.g. 2103).")
                return 2
            resp = vci.send_command(raw_bytes[:2], raw_bytes[2:])
            if not resp:
                print("No response.")
                return 1
            print(f"RX cmd={resp.cmd.hex(' ').upper()} checksum_ok={resp.checksum_ok}")
            print(f"RX data={resp.data.hex(' ').upper()}")
            print(f"RX raw ={resp.raw.hex(' ').upper()}")
            return 0

        info = vci.get_adapter_info()
        fw = vci.get_firmware_versions()
        print(f"Serial Number : {info['serial_number']}")
        print(f"Chip ID       : {info['chip_id']}")
        print(f"Versions      : {', '.join(fw['versions'])}")
        print(f"Checksums OK  : {info['checksum_ok'] and fw['checksum_ok']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
