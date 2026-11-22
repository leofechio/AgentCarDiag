"""Pure calculations for CAN bus utilization and observed frame errors.

Integration contract
--------------------
The acquisition layer passes an iterable of frame mappings to
``calculate_can_telemetry``. Each data frame has ``data_length`` (0–8), with
optional boolean ``is_extended`` and ``is_error`` fields. Supply the bitrate
and duration for the same observation window. The returned mapping contains
``bus_load_pct``, ``error_pct``, ``frame_count``, ``error_frame_count``, and
``estimated_occupied_bits``; it can be added to an API response or merged into
the existing CAN telemetry dictionary consumed by ``DiagnosticEngine``.

This module has no acquisition, web, or diagnostic-engine dependencies so the
same calculation can be used by live adapters and tests. Load is estimated
from nominal Classical CAN frame lengths, excluding bit stuffing,
retransmissions, and controller-specific framing. Error frames contribute to
the error-rate denominator but not the estimated occupied bits because their
wire duration depends on controller and error state. Callers must provide one
consistent observation window and bitrate.
"""

from collections.abc import Iterable, Mapping
from numbers import Real
from typing import Any


def _finite_positive(value: Real, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    result = float(value)
    if result <= 0 or result == float("inf") or result != result:
        raise ValueError(f"{name} must be finite and greater than zero")
    return result


def _frame_value(frame: Mapping[str, Any], key: str, default: Any) -> Any:
    value = frame.get(key, default)
    return value


def estimate_frame_bits(data_length: int, *, is_extended: bool = False) -> int:
    """Return nominal Classical CAN frame bits including intermission, no stuffing.

    Standard frames use 47 fixed bits plus payload bits; extended frames use
    67 fixed bits. This deliberately models Classical CAN (0–8 data bytes).
    """
    if isinstance(data_length, bool) or not isinstance(data_length, int):
        raise TypeError("data_length must be an integer")
    if not 0 <= data_length <= 8:
        raise ValueError("Classical CAN data_length must be between 0 and 8")
    if not isinstance(is_extended, bool):
        raise TypeError("is_extended must be a boolean")
    return (67 if is_extended else 47) + 8 * data_length


def calculate_can_telemetry(
    frames: Iterable[Mapping[str, Any]],
    *,
    bitrate: Real,
    window_seconds: Real,
) -> dict[str, float | int]:
    """Calculate estimated bus load and frame error percentage.

    Each mapping requires ``data_length`` (0–8); ``is_extended`` and
    ``is_error`` default to False. Error frames count in the error-rate
    denominator but do not add estimated occupied bits, as their actual wire
    duration depends on the controller and error state.
    """
    bit_rate = _finite_positive(bitrate, "bitrate")
    window = _finite_positive(window_seconds, "window_seconds")
    capacity_bits = bit_rate * window
    if capacity_bits == 0:
        raise ValueError("bitrate * window_seconds must be greater than zero")
    total = errors = occupied_bits = 0

    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise TypeError(f"frame at index {index} must be a mapping")
        is_error = _frame_value(frame, "is_error", False)
        if not isinstance(is_error, bool):
            raise TypeError(f"is_error at index {index} must be a boolean")
        total += 1
        if is_error:
            errors += 1
            continue
        data_length = _frame_value(frame, "data_length", None)
        if data_length is None:
            raise ValueError(f"frame at index {index} is missing data_length")
        extended = _frame_value(frame, "is_extended", False)
        occupied_bits += estimate_frame_bits(data_length, is_extended=extended)

    bus_load_pct = min(100.0, occupied_bits / capacity_bits * 100.0)
    error_pct = errors / total * 100.0 if total else 0.0
    return {
        "bus_load_pct": bus_load_pct,
        "error_pct": error_pct,
        "frame_count": total,
        "error_frame_count": errors,
        "estimated_occupied_bits": occupied_bits,
    }
