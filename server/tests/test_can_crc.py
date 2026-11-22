import pytest

from app.can_crc import calculate_can_crc, calculate_can_crc_bits


def test_crc15_can_check_value_for_ascii_123456789():
    # CRC-15/CAN: poly=0x4599, init=0, refin=false, xorout=0.
    assert calculate_can_crc(b"123456789") == 0x059E


def test_bytes_are_processed_most_significant_bit_first():
    assert calculate_can_crc(b"\x80") == calculate_can_crc_bits([1, 0, 0, 0, 0, 0, 0, 0])


@pytest.mark.parametrize("data", [bytearray(b"123456789"), memoryview(b"123456789")])
def test_crc_accepts_mutable_and_view_bytes_like_inputs(data):
    assert calculate_can_crc(data) == 0x059E


def test_bits_support_a_non_byte_aligned_protected_stream():
    assert calculate_can_crc_bits([1, 0, 1]) == calculate_can_crc_bits(iter([1, 0, 1]))


def test_empty_input_has_zero_remainder():
    assert calculate_can_crc(b"") == 0
    assert calculate_can_crc_bits([]) == 0


@pytest.mark.parametrize("bit", [2, -1])
def test_bit_calculation_rejects_values_outside_binary_alphabet(bit):
    with pytest.raises(ValueError, match="must be 0 or 1"):
        calculate_can_crc_bits([bit])


@pytest.mark.parametrize("bit", [True, 1.0, "1", None])
def test_bit_calculation_rejects_non_integer_bits(bit):
    with pytest.raises(TypeError, match="integer 0 or 1"):
        calculate_can_crc_bits([bit])


@pytest.mark.parametrize("data", ["123", [1, 2, 3], None])
def test_byte_calculation_requires_bytes_like_input(data):
    with pytest.raises(TypeError, match="bytes-like"):
        calculate_can_crc(data)
