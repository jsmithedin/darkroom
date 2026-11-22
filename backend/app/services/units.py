"""Pure maths for derived figures. No database, no I/O."""

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

TENTH = Decimal("0.1")


def stops_vs_box(ei: Decimal, box_iso: int) -> Decimal:
    """Stops of over- (+) or under- (-) exposure relative to the box speed: log2(EI / box ISO).

    Rounded to one decimal place, halves away from zero.
    """
    if ei <= 0 or box_iso <= 0:
        raise ValueError("EI and box ISO must be positive")
    stops = Decimal(repr(math.log2(float(ei) / box_iso)))
    return stops.quantize(TENTH, rounding=ROUND_HALF_UP)


def format_stops(stops: Decimal) -> str:
    """'+1', '-2', '0', '-0.7': a sign, and a decimal only when there is a fractional part."""
    rounded = stops.quantize(TENTH, rounding=ROUND_HALF_UP)
    if rounded == 0:
        return "0"
    text = f"{abs(rounded):f}"
    if rounded == rounded.to_integral_value():
        text = str(int(abs(rounded)))
    return ("+" if rounded > 0 else "-") + text


def cassette_mm(leader_mm: int, pitch_mm: int, exposures: int) -> int:
    """Film used to fill one cassette: a leader plus one frame pitch per exposure."""
    return leader_mm + exposures * pitch_mm


@dataclass(frozen=True)
class BulkDerived:
    cassettes_loaded: int
    used_mm: int
    left_mm: int  # negative when the spool is overdrawn; kept so the shortfall is visible
    exposures_left: int  # never below zero
    cost_per_36_pence: int | None  # None when the spool has no price


def bulk_derived(
    length_mm: int,
    cost_pence: int | None,
    used_before_mm: int,
    loads: list[tuple[int, int]],
    leader_mm: int,
    pitch_mm: int,
) -> BulkDerived:
    """Everything derived from a bulk spool. Integer arithmetic throughout.

    `loads` is a list of `(rolls, metres_mm)`, the stored snapshot of each bulk load.
    """
    if length_mm <= 0 or leader_mm <= 0 or pitch_mm <= 0:
        raise ValueError("length, leader and frame pitch must be positive")
    used = used_before_mm + sum(metres for _, metres in loads)
    left = length_mm - used
    exposures_left = max(0, (left - leader_mm) // pitch_mm)  # floor division

    cost_per_36 = None
    if cost_pence is not None:
        # cost / (length / cassette36), rounded half up to the penny, without floats
        cassette36 = cassette_mm(leader_mm, pitch_mm, 36)
        cost_per_36 = (2 * cost_pence * cassette36 + length_mm) // (2 * length_mm)

    return BulkDerived(
        cassettes_loaded=sum(rolls for rolls, _ in loads),
        used_mm=used,
        left_mm=left,
        exposures_left=exposures_left,
        cost_per_36_pence=cost_per_36,
    )
