"""CRC-15/CAN calculation helpers.

The checksum is calculated over the unstuffed, MSB-first protected bit stream
using CRC-15/CAN (width 15, polynomial 0x4599, init/xorout 0). For a complete
Classical CAN frame, callers must provide SOF through the final data bit; the
CRC field, delimiter, ACK, EOF, and intermission are excluded. This module
does not parse frame identifiers or perform bit stuffing.
"""

from collections.abc import Iterable

CRC15_CAN_WIDTH = 15
CRC15_CAN_POLY = 0x4599
CRC15_CAN_MASK = (1 << CRC15_CAN_WIDTH) - 1


def calculate_can_crc_bits(bits: Iterable[int]) -> int:
    """Return CRC-15/CAN for a sequence of unstuffed bits, in wire order.

    Each input must be an integer 0 or 1. The first bit is processed first;
    there is no reflection or final XOR.
    """
    crc = 0
    for index, bit in enumerate(bits):
        if isinstance(bit, bool) or not isinstance(bit, int):
            raise TypeError(f"bit at index {index} must be an integer 0 or 1")
        if bit not in (0, 1):
            raise ValueError(f"bit at index {index} must be 0 or 1")
        feedback = ((crc >> (CRC15_CAN_WIDTH - 1)) & 1) ^ bit
        crc = (crc << 1) & CRC15_CAN_MASK
        if feedback:
            crc ^= CRC15_CAN_POLY
    return crc


def calculate_can_crc(data: bytes | bytearray | memoryview) -> int:
    """Return CRC-15/CAN over bytes, processing each byte most-significant bit first.

    This byte-oriented form is useful when the protected bit stream is byte
    aligned. For a packed frame with a partial final byte, use
    :func:`calculate_can_crc_bits` to avoid including padding bits.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    return calculate_can_crc_bits(
        (byte >> shift) & 1
        for byte in data
        for shift in range(7, -1, -1)
    )
