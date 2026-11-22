import pytest

from app.services.units import BulkDerived, bulk_derived, cassette_mm

LEADER, PITCH = 250, 38


@pytest.mark.parametrize(
    ("exposures", "expected"),
    [(36, 1618), (24, 1162), (12, 706), (0, 250), (1, 288)],
)
def test_cassette_mm(exposures: int, expected: int) -> None:
    assert cassette_mm(LEADER, PITCH, exposures) == expected


def derive(**over: object) -> BulkDerived:
    args: dict[str, object] = {
        "length_mm": 17_000,
        "cost_pence": None,
        "used_before_mm": 9_700,
        "loads": [],
        "leader_mm": LEADER,
        "pitch_mm": PITCH,
    }
    args.update(over)
    return bulk_derived(**args)  # type: ignore[arg-type]


def test_bulk_1_from_the_sheet() -> None:
    d = derive()
    assert d == BulkDerived(
        cassettes_loaded=0, used_mm=9_700, left_mm=7_300, exposures_left=185, cost_per_36_pence=None
    )


def test_loads_reduce_what_is_left() -> None:
    # two 36-exposure cassettes
    d = derive(loads=[(2, 2 * 1618)])
    assert d.cassettes_loaded == 2
    assert d.used_mm == 9_700 + 3_236
    assert d.left_mm == 17_000 - 12_936  # 4064
    assert d.exposures_left == 100  # (4064 - 250) // 38


def test_several_loads_sum() -> None:
    d = derive(loads=[(1, 1618), (3, 3 * 1162), (1, 706)])
    assert d.cassettes_loaded == 5
    assert d.used_mm == 9_700 + 1618 + 3486 + 706


@pytest.mark.parametrize(
    ("left", "expected"),
    [(288, 1), (287, 0), (250, 0), (249, 0), (0, 0), (538, 7), (539, 7), (7_300, 185)],
)
def test_exposures_left_floors_and_clamps(left: int, expected: int) -> None:
    d = derive(used_before_mm=17_000 - left)
    assert d.left_mm == left
    assert d.exposures_left == expected


def test_overdrawn_spool_clamps_exposures_but_keeps_negative_left() -> None:
    d = derive(loads=[(5, 5 * 1618)])  # 9700 + 8090 = 17790 > 17000
    assert d.left_mm == -790
    assert d.exposures_left == 0
    assert d.used_mm == 17_790


def test_unpriced_spool_has_no_cost() -> None:
    assert derive().cost_per_36_pence is None
    assert derive(cost_pence=None).cost_per_36_pence is None


@pytest.mark.parametrize(
    ("length", "cost", "expected"),
    [
        (17_000, 1_700, 162),  # 1618/17000 * 1700 = 161.8
        (17_000, 0, 0),  # a free spool
        (30_480, 3_000, 159),  # 100 ft: 1618/30480 * 3000 = 159.25
        (1_618, 500, 500),  # exactly one 36-exposure cassette
        (3_236, 1_001, 501),  # 500.5 rounds half up
    ],
)
def test_cost_per_36_rounds_to_the_penny(length: int, cost: int, expected: int) -> None:
    assert derive(length_mm=length, cost_pence=cost, used_before_mm=0).cost_per_36_pence == expected


def test_cost_per_36_follows_current_settings() -> None:
    cheaper = derive(cost_pence=1_700, leader_mm=100, pitch_mm=30)  # 36 exposures = 1180 mm
    assert cheaper.cost_per_36_pence == 118


@pytest.mark.parametrize(
    "over",
    [{"length_mm": 0}, {"length_mm": -1}, {"leader_mm": 0}, {"pitch_mm": 0}],
)
def test_rejects_non_positive_inputs(over: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        derive(**over)
