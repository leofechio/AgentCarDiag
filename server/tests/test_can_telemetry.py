import math

import pytest

from app.can_telemetry import calculate_can_telemetry, estimate_frame_bits


@pytest.mark.parametrize(
    ("data_length", "is_extended", "expected_bits"),
    [
        (0, False, 47),
        (8, False, 111),
        (0, True, 67),
        (8, True, 131),
    ],
)
def test_estimate_frame_bits_for_classical_can_frames(data_length, is_extended, expected_bits):
    assert estimate_frame_bits(data_length, is_extended=is_extended) == expected_bits


@pytest.mark.parametrize("data_length", [-1, 9])
def test_estimate_frame_bits_rejects_payload_lengths_outside_classical_can(data_length):
    with pytest.raises(ValueError, match="between 0 and 8"):
        estimate_frame_bits(data_length)


@pytest.mark.parametrize("data_length", [1.5, "8", None, True])
def test_estimate_frame_bits_rejects_non_integer_lengths(data_length):
    with pytest.raises(TypeError, match="integer"):
        estimate_frame_bits(data_length)


def test_estimate_frame_bits_requires_boolean_extended_flag():
    with pytest.raises(TypeError, match="boolean"):
        estimate_frame_bits(8, is_extended=1)


def test_calculates_bus_load_and_counts_standard_and_extended_frames():
    metrics = calculate_can_telemetry(
        [{"data_length": 8}, {"data_length": 8, "is_extended": True}],
        bitrate=500_000,
        window_seconds=1,
    )

    assert metrics == {
        "bus_load_pct": pytest.approx(0.0484),
        "error_pct": 0.0,
        "frame_count": 2,
        "error_frame_count": 0,
        "estimated_occupied_bits": 242,
    }


def test_error_percentage_uses_all_observed_frames_and_excludes_error_bits_from_load():
    metrics = calculate_can_telemetry(
        [
            {"data_length": 8},
            {"data_length": 4},
            {"is_error": True},
            {"is_error": True},
        ],
        bitrate=500_000,
        window_seconds=1,
    )

    assert metrics["frame_count"] == 4
    assert metrics["error_frame_count"] == 2
    assert metrics["error_pct"] == 50.0
    assert metrics["estimated_occupied_bits"] == 190


def test_empty_window_returns_zero_counts_and_percentages():
    metrics = calculate_can_telemetry([], bitrate=500_000, window_seconds=1)

    assert metrics["bus_load_pct"] == 0.0
    assert metrics["error_pct"] == 0.0
    assert metrics["frame_count"] == 0
    assert metrics["error_frame_count"] == 0
    assert metrics["estimated_occupied_bits"] == 0


def test_caps_bus_load_at_one_hundred_percent():
    metrics = calculate_can_telemetry(
        [{"data_length": 8}] * 100, bitrate=100, window_seconds=1
    )

    assert metrics["bus_load_pct"] == 100.0


def test_accepts_generator_of_frames():
    frames = ({"data_length": size} for size in (0, 1))

    metrics = calculate_can_telemetry(frames, bitrate=1_000, window_seconds=1)

    assert metrics["frame_count"] == 2
    assert metrics["estimated_occupied_bits"] == 102


@pytest.mark.parametrize("value", [0, -1, math.inf, -math.inf, math.nan])
def test_rejects_non_positive_or_non_finite_bitrate(value):
    with pytest.raises(ValueError, match="finite and greater than zero"):
        calculate_can_telemetry([], bitrate=value, window_seconds=1)


@pytest.mark.parametrize("value", [0, -1, math.inf, -math.inf, math.nan])
def test_rejects_non_positive_or_non_finite_window(value):
    with pytest.raises(ValueError, match="finite and greater than zero"):
        calculate_can_telemetry([], bitrate=500_000, window_seconds=value)


def test_rejects_capacity_that_underflows_to_zero():
    with pytest.raises(ValueError, match=r"bitrate \* window_seconds"):
        calculate_can_telemetry([], bitrate=5e-324, window_seconds=0.5)


@pytest.mark.parametrize("value", ["500000", None, True])
def test_rejects_non_real_bitrate(value):
    with pytest.raises(TypeError, match="real number"):
        calculate_can_telemetry([], bitrate=value, window_seconds=1)


@pytest.mark.parametrize("frame", [None, [], "frame"])
def test_rejects_non_mapping_frame(frame):
    with pytest.raises(TypeError, match="must be a mapping"):
        calculate_can_telemetry([frame], bitrate=500_000, window_seconds=1)


def test_rejects_non_error_frame_without_data_length():
    with pytest.raises(ValueError, match="missing data_length"):
        calculate_can_telemetry([{}], bitrate=500_000, window_seconds=1)


@pytest.mark.parametrize("is_error", [0, "yes", None])
def test_rejects_non_boolean_error_flag(is_error):
    with pytest.raises(TypeError, match="is_error.*boolean"):
        calculate_can_telemetry(
            [{"data_length": 8, "is_error": is_error}],
            bitrate=500_000,
            window_seconds=1,
        )


def test_error_frame_does_not_require_payload_length():
    metrics = calculate_can_telemetry(
        [{"is_error": True}], bitrate=500_000, window_seconds=1
    )

    assert metrics["error_pct"] == 100.0
    assert metrics["estimated_occupied_bits"] == 0


def test_rejects_invalid_extended_flag_on_data_frame():
    with pytest.raises(TypeError, match="boolean"):
        calculate_can_telemetry(
            [{"data_length": 8, "is_extended": 1}],
            bitrate=500_000,
            window_seconds=1,
        )
