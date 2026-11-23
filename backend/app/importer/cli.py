"""Import the sheet's CSV exports: `uv run python -m app.importer.cli ./import`.

Everything runs in one transaction. The reconciliation is checked before committing, so a
mismatch leaves the database untouched. Use `--dry-run` to check without committing.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.importer.load import LoadError, UnknownNames, load_all
from app.importer.parse import ParseError, parse_all
from app.importer.reconcile import Expected, reconcile
from app.models import User
from app.services.stock import InsufficientStockError


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{tab} {n}" for tab, n in counts.items()) or "nothing"


async def import_folder(
    session: AsyncSession, folder: Path, expected: Expected, dry_run: bool = False
) -> tuple[int, list[str]]:
    """Run the import. Returns (exit code, lines to print): 0 ok, 1 mismatch, 2 bad input."""
    out: list[str] = []
    try:
        sheet = parse_all(folder)
    except ParseError as exc:
        return 2, ["Could not read the exports:", *(f"  {p}" for p in exc.problems)]
    user_id = (
        await session.execute(select(User.id).order_by(User.created_at).limit(1))
    ).scalar_one_or_none()
    if user_id is None:
        return 2, ["No user exists yet: sign in to the app once, then run the import again."]
    try:
        report = await load_all(session, sheet, user_id, commit=False)
    except UnknownNames as exc:
        return 2, [
            "Unknown names, nothing imported:",
            *(f"  {k}: {', '.join(v)}" for k, v in exc.unknown.items()),
        ]
    except LoadError as exc:
        return 2, [f"Import refused, nothing imported: {exc}"]
    except InsufficientStockError as exc:
        return 2, [
            "Import refused, nothing imported: stock of "
            f"{exc.film_name} ({exc.format_name}) would go below zero."
        ]
    out.append(
        "Inserted: " + (", ".join(f"{t} {n}" for t, n in report.inserted.items()) or "nothing")
    )
    out.append(
        "Already imported: "
        + (", ".join(f"{t} {n}" for t, n in report.skipped.items()) or "nothing")
    )
    figures = await reconcile(session)
    out.append(figures.report())
    problems = figures.check(expected)
    if problems:
        await session.rollback()
        return 1, [*out, "Reconciliation FAILED, nothing imported:", *(f"  {p}" for p in problems)]
    if dry_run:
        await session.rollback()
        return 0, [*out, "Reconciliation matches. Dry run: nothing committed."]
    await session.commit()
    return 0, [*out, "Reconciliation matches. Imported."]


async def _main(folder: Path, dry_run: bool) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            code, lines = await import_folder(session, folder, Expected(), dry_run)
    finally:
        await engine.dispose()
    print("\n".join(lines))
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the Film Photography Tracker exports.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="check, then roll back")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.folder, args.dry_run)))


if __name__ == "__main__":
    main()
