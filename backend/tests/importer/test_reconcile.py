import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.importer.cli import import_folder
from app.importer.reconcile import Expected, Reconciliation, reconcile
from app.models import Roll, User

GOOD = Reconciliation(
    total_rolls=117,
    rolls_per_year={2025: 60, 2026: 57},
    stock_by_format={"35mm": 61, "120": 88},
    bulk_left_mm={"Bulk 1": 7300},
)


def test_matching_report_returns_empty() -> None:
    assert GOOD.check(Expected()) == []


def test_check_reports_each_mismatch() -> None:
    bad = Reconciliation(
        total_rolls=116,
        rolls_per_year={2025: 59, 2026: 57, 2027: 1},
        stock_by_format={"35mm": 60, "120": 88},
        bulk_left_mm={"Bulk 1": 7000},
    )
    assert bad.check(Expected()) == [
        "total rolls: expected 117, got 116",
        "rolls in 2025: expected 60, got 59",
        "rolls in 2027: expected 0, got 1",
        "stock of 35mm: expected 61, got 60",
        "Bulk 1 left (mm): expected 7300, got 7000",
    ]


def test_report_is_readable() -> None:
    assert "Bulk left: Bulk 1: 7.3 m" in GOOD.report()


TABS = {
    "Tracker.csv": (
        "Dev date,Camera,Lens,Format,Film,EI,Developer\n"
        "01/01/2025,Nikon,N/A,35mm,Tri-X,400,HC-110\n"
        "02/01/2026,Nikon,N/A,35mm,Tri-X,400,HC-110\n"
    ),
    "Films.csv": "Film,Type,Box ISO,Opening 35mm,Opening 120\nTri-X,bw,400,5,0\n",
    "Lists.csv": "Cameras,Lenses,Formats,Developers,Filters\nNikon,N/A,35mm,HC-110,Yellow\n",
    "Bulk.csv": "ID,Film,Length (mm),Used before tracking (mm)\nBulk 1,Tri-X,10000,2000\n",
    "Purchases.csv": "Date,Rolls\n",
    "Dev Times.csv": "Film,EI,Developer,Time (min)\n",
}
MATCHING = Expected(
    total_rolls=2,
    rolls_per_year={2025: 1, 2026: 1},
    stock_by_format={"35mm": 5},
    bulk_left_mm={"Bulk 1": 8000},
)


async def sheet_folder(tmp_path: Path, db: AsyncSession) -> Path:
    db.add(User(email=f"{uuid.uuid4()}@example.com", name="Me", google_sub="s" + uuid.uuid4().hex))
    await db.flush()
    for name, text in TABS.items():
        (tmp_path / name).write_text(text)
    return tmp_path


async def roll_count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(Roll))).scalar_one())


async def test_import_commits_when_the_figures_match(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    folder = await sheet_folder(tmp_path, db_session)
    code, lines = await import_folder(db_session, folder, MATCHING)
    assert code == 0, lines
    assert lines[-1] == "Reconciliation matches. Imported."
    assert await roll_count(db_session) == 2
    code, lines = await import_folder(db_session, folder, MATCHING)
    assert code == 0 and "Inserted: nothing" in lines


async def test_mismatch_imports_nothing_and_fails(db_session: AsyncSession, tmp_path: Path) -> None:
    folder = await sheet_folder(tmp_path, db_session)
    wrong = Expected(**{**MATCHING.__dict__, "total_rolls": 3})
    code, lines = await import_folder(db_session, folder, wrong)
    assert code == 1
    assert "  total rolls: expected 3, got 2" in lines
    assert await roll_count(db_session) == 0


async def test_dry_run_commits_nothing(db_session: AsyncSession, tmp_path: Path) -> None:
    folder = await sheet_folder(tmp_path, db_session)
    code, lines = await import_folder(db_session, folder, MATCHING, dry_run=True)
    assert code == 0 and lines[-1].endswith("nothing committed.")
    assert await roll_count(db_session) == 0


async def test_unknown_names_exit_with_the_list(db_session: AsyncSession, tmp_path: Path) -> None:
    folder = await sheet_folder(tmp_path, db_session)
    (folder / "Lists.csv").write_text(
        "Cameras,Lenses,Formats,Developers,Filters\nLeica,N/A,35mm,HC-110,\n"
    )
    code, lines = await import_folder(db_session, folder, MATCHING)
    assert code == 2 and "  camera: Nikon" in lines


async def test_overdrawn_stock_is_refused_with_exit_2(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    folder = await sheet_folder(tmp_path, db_session)
    (folder / "Tracker.csv").write_text(
        "Dev date,Camera,Lens,Format,Film,EI,Developer\n"
        + "01/12/2026,Nikon,N/A,35mm,Tri-X,400,HC-110\n" * 6
    )
    code, lines = await import_folder(db_session, folder, MATCHING)
    assert code == 2
    assert lines == ["Import refused, nothing imported: stock of Tri-X (35mm) would go below zero."]


async def test_missing_files_are_reported(db_session: AsyncSession, tmp_path: Path) -> None:
    code, lines = await import_folder(db_session, tmp_path, MATCHING)
    assert code == 2 and "Could not read the exports:" in lines[0]


async def test_reconcile_reads_the_database(db_session: AsyncSession) -> None:
    figures = await reconcile(db_session)
    assert figures.total_rolls == 0 and figures.bulk_left_mm == {}


async def test_rolls_already_in_the_app_do_not_disturb_the_check(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    from datetime import date

    from app.models import Camera, Developer, Film, Format

    folder = await sheet_folder(tmp_path, db_session)
    fmt = Format(name="4x5")
    db_session.add_all([fmt, Camera(name="App cam"), Developer(name="App dev")])
    film = Film(name="App film", type="bw", box_iso=100)
    db_session.add(film)
    await db_session.flush()
    cam = (await db_session.execute(select(Camera))).scalar_one()
    dev = (await db_session.execute(select(Developer))).scalar_one()
    # Deliberately unstocked (4x5 stock is -1): this is the live database's state that the
    # first real import hit, and the import's own figures must not notice it.
    db_session.add(
        Roll(
            dev_date=date(2026, 11, 23),
            camera_id=cam.id,
            format_id=fmt.id,
            film_id=film.id,
            ei=100,
            developer_id=dev.id,
        )
    )
    await db_session.flush()
    code, lines = await import_folder(db_session, folder, MATCHING)
    assert code == 0, lines
    assert "(1 roll(s) already in the database are not part of this check)" in lines
