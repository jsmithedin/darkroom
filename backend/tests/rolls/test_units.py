from decimal import Decimal

import pytest

from app.services.units import format_stops, stops_vs_box


@pytest.mark.parametrize(
    ("ei", "box", "expected_stops", "shown"),
    [
        ("400", 400, "0.0", "0"),
        ("800", 400, "1.0", "+1"),
        ("100", 400, "-2.0", "-2"),
        ("3200", 400, "3.0", "+3"),
        ("250", 400, "-0.7", "-0.7"),
        ("200", 400, "-1.0", "-1"),
        ("320", 400, "-0.3", "-0.3"),
        ("560", 400, "0.5", "+0.5"),
        ("50", 100, "-1.0", "-1"),
        ("402", 400, "0.0", "0"),  # rounds to zero, never "-0" or "+0"
        ("398", 400, "0.0", "0"),
        ("200.5", 400, "-1.0", "-1"),
    ],
)
def test_stops_vs_box(ei: str, box: int, expected_stops: str, shown: str) -> None:
    stops = stops_vs_box(Decimal(ei), box)
    assert stops == Decimal(expected_stops)
    assert format_stops(stops) == shown


@pytest.mark.parametrize(
    ("value", "shown"),
    [("0", "0"), ("-0.0", "0"), ("1", "+1"), ("-1", "-1"), ("2.5", "+2.5"), ("-0.7", "-0.7")],
)
def test_format_stops(value: str, shown: str) -> None:
    assert format_stops(Decimal(value)) == shown


@pytest.mark.parametrize(("ei", "box"), [("0", 400), ("-1", 400), ("400", 0)])
def test_stops_vs_box_rejects_non_positive(ei: str, box: int) -> None:
    with pytest.raises(ValueError):
        stops_vs_box(Decimal(ei), box)
