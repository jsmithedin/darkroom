"""Pure maths for derived figures. No database, no I/O."""

import math
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
