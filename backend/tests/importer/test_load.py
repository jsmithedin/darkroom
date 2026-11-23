import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.importer.load import UnknownNames, fingerprint, load_all
from app.importer.parse import (
    OPENING_DATE,
    BulkRow,
    FilmRow,
    ListsData,
    OpeningRow,
    ParsedSheet,
    PurchaseRow,
    RollRow,
)
from app.models import BulkRoll, Camera, Film, ImportLedger, Roll, StockMovement, User
from app.services.stock import current_stock


def roll(day: date = date(2026, 4, 19), **over: object) -> RollRow:
    values: dict[str, object] = {
        "line": 3,
        "dev_date": day,
        "camera": "Nikon FM2",
        "lens": "50mm f/1.8",
        "format": "35mm",
        "film": "Tri-X",
        "ei": Decimal("400"),
        "developer": "HC-110",
        "dev_time_min": None,
        "filter": None,
        "subject": None,
        "notes": None,
        "source": "factory",
    }
    return RollRow(**{**values, **over})  # type: ignore[arg-type]


def sheet(**over: object) -> ParsedSheet:
    values: dict[str, object] = {
        "tracker": [roll(), roll(), roll(date(2026, 5, 1), camera="nikon fm2")],
        "films": [
            FilmRow(2, "Tri-X", "bw", 400),
            FilmRow(3, "Fomapan 100", "bw", 100),
        ],
        "openings": [OpeningRow(2, "Tri-X", "35mm", 10, OPENING_DATE)],
        "lists": ListsData(
            cameras=["Nikon FM2"],
            lenses=["50mm f/1.8"],
            formats=["35mm", "120"],
            developers=["HC-110"],
            filters=["Yellow"],
        ),
        "bulk": [BulkRow(2, "Bulk 1", "Fomapan 100", 17000, 9700, None, None, None, None)],
        "purchases": [],
        "dev_times": [],
    }
    return ParsedSheet(**{**values, **over})  # type: ignore[arg-type]


@pytest.fixture
async def actor(db_session: AsyncSession) -> object:
    user = User(email=f"{uuid.uuid4()}@example.com", name="Me", google_sub=str(uuid.uuid4()))
    db_session.add(user)
    await db_session.flush()
    return user.id


async def count(db: AsyncSession, model: type) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


def test_fingerprint_is_stable_and_depends_on_tab_and_content() -> None:
    row = {"a": "1", "b": "2"}
    assert fingerprint("tracker", row) == fingerprint("tracker", {"b": "2", "a": "1"})
    assert fingerprint("tracker", row) != fingerprint("bulk", row)
    assert fingerprint("tracker", row) != fingerprint("tracker", {"a": "1", "b": "3"})


async def test_identical_rows_kept_once_each(db_session: AsyncSession, actor: object) -> None:
    first = await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    assert first.inserted["tracker"] == 3
    # The two identical rows are two rolls; the third differs only by name case and date.
    assert await count(db_session, Roll) == 3
    again = await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    assert await count(db_session, Roll) == 3
    assert again.total_inserted == 0


async def test_second_run_inserts_nothing(db_session: AsyncSession, actor: object) -> None:
    await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    before = {m: await count(db_session, m) for m in (Roll, Film, Camera, BulkRoll, StockMovement)}
    ledger = await count(db_session, ImportLedger)
    report = await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    assert report.total_inserted == 0
    assert sum(report.skipped.values()) == ledger
    assert before == {
        m: await count(db_session, m) for m in (Roll, Film, Camera, BulkRoll, StockMovement)
    }
    assert await count(db_session, ImportLedger) == ledger


async def test_extra_identical_row_on_rerun_is_added_once(
    db_session: AsyncSession, actor: object
) -> None:
    await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    more = sheet(tracker=[roll(), roll(), roll(), roll(date(2026, 5, 1), camera="nikon fm2")])
    report = await load_all(db_session, more, actor)  # type: ignore[arg-type]
    assert report.inserted == {"tracker": 1}
    assert await count(db_session, Roll) == 4


async def test_unknown_names_abort_listing_all_and_insert_nothing(
    db_session: AsyncSession, actor: object
) -> None:
    bad = sheet(
        tracker=[
            roll(camera="Leica M6"),
            roll(lens="Summicron", film="HP5"),
            roll(developer="D-76", filter="Red", format="4x5"),
        ]
    )
    with pytest.raises(UnknownNames) as caught:
        await load_all(db_session, bad, actor)  # type: ignore[arg-type]
    assert caught.value.unknown == {
        "camera": ["Leica M6"],
        "lens": ["Summicron"],
        "film": ["HP5"],
        "developer": ["D-76"],
        "filter": ["Red"],
        "format": ["4x5"],
    }
    for model in (Roll, Film, Camera, BulkRoll, StockMovement, ImportLedger):
        assert await count(db_session, model) == 0


async def test_imported_rolls_do_not_change_stock(db_session: AsyncSession, actor: object) -> None:
    await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    film = (await db_session.execute(select(Film).where(Film.name == "Tri-X"))).scalar_one()
    fmt = (await db_session.execute(select(Roll.format_id).limit(1))).scalar_one()
    assert await current_stock(db_session, film.id, fmt) == 10  # the opening count only
    flags = (await db_session.execute(select(Roll.counts_against_stock))).scalars().all()
    assert flags == [False] * 3


async def test_rolls_after_the_opening_date_count(db_session: AsyncSession, actor: object) -> None:
    s = sheet(tracker=[roll(date(2026, 11, 23))])
    await load_all(db_session, s, actor)  # type: ignore[arg-type]
    film = (await db_session.execute(select(Film).where(Film.name == "Tri-X"))).scalar_one()
    fmt = (await db_session.execute(select(Roll.format_id))).scalar_one()
    assert await current_stock(db_session, film.id, fmt) == 9


async def test_opening_movements_dated_2026_11_22(db_session: AsyncSession, actor: object) -> None:
    await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    rows = (await db_session.execute(select(StockMovement))).scalars().all()
    assert [(m.kind, m.occurred_on, m.rolls) for m in rows] == [("opening", date(2026, 11, 22), 10)]


async def test_bulk_1_imported_unpriced(db_session: AsyncSession, actor: object) -> None:
    await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    spool = (await db_session.execute(select(BulkRoll))).scalar_one()
    assert (spool.label, spool.length_mm, spool.used_before_mm) == ("Bulk 1", 17000, 9700)
    assert (spool.cost_pence, spool.supplier, spool.bought_on) == (None, None, None)


async def test_existing_reference_items_are_reused(db_session: AsyncSession, actor: object) -> None:
    db_session.add(Camera(name="NIKON FM2"))
    await db_session.flush()
    await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    assert await count(db_session, Camera) == 1


async def test_purchases_given_away_and_bulk_load(db_session: AsyncSession, actor: object) -> None:
    purchases = [
        PurchaseRow(
            2, "purchase", date(2026, 11, 25), "Tri-X", "35mm", 5, 2500, "Shop", None, None, None
        ),
        PurchaseRow(
            3, "given_away", date(2026, 11, 26), "Tri-X", "35mm", -2, None, None, None, None, "Gift"
        ),
        PurchaseRow(
            4, "bulk_load", date(2026, 11, 27), None, None, 2, None, None, "Bulk 1", 36, None
        ),
    ]
    await load_all(db_session, sheet(purchases=purchases), actor)  # type: ignore[arg-type]
    kinds = (
        (await db_session.execute(select(StockMovement.kind).order_by(StockMovement.occurred_on)))
        .scalars()
        .all()
    )
    assert kinds == ["opening", "purchase", "given_away", "bulk_load"]
    load = (
        await db_session.execute(select(StockMovement).where(StockMovement.kind == "bulk_load"))
    ).scalar_one()
    assert load.metres_mm == 2 * (250 + 36 * 38)  # leader 250, pitch 38 at import time


async def test_blank_and_text_none_have_different_fingerprints() -> None:
    from app.importer.load import _fields

    assert fingerprint("t", _fields(roll(notes=None))) != fingerprint(
        "t", _fields(roll(notes="None"))
    )


async def test_renamed_reference_item_still_resolves_on_rerun(
    db_session: AsyncSession, actor: object
) -> None:
    await load_all(db_session, sheet(), actor)  # type: ignore[arg-type]
    camera = (await db_session.execute(select(Camera))).scalar_one()
    camera.name = "Nikon FM2 (black)"
    await db_session.flush()
    more = sheet(
        tracker=[
            roll(),
            roll(),
            roll(date(2026, 5, 1), camera="nikon fm2"),
            roll(day=date(2026, 6, 1)),
        ]
    )
    report = await load_all(db_session, more, actor)  # type: ignore[arg-type]
    assert report.inserted == {"tracker": 1}
    assert await count(db_session, Camera) == 1
