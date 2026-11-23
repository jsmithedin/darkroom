"""Load a parsed sheet into the database, once, in one transaction.

Every row is recorded in `import_ledger` under (tab, fingerprint, occurrence), so a second run
inserts nothing, yet identical rows (several rolls on one day) are each kept. Names are checked
against the reference data first: any unknown camera, lens, film, developer, filter or format
aborts the run before anything is written, listing all of them.
"""

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.importer.parse import OPENING_DATE, ParsedSheet
from app.models import (
    BulkRoll,
    Camera,
    Developer,
    Film,
    Filter,
    Format,
    ImportLedger,
    Lens,
    Roll,
    StockMovement,
)
from app.models.reference import NamedItem
from app.services.settings import get_settings
from app.services.stock import Pair, assert_non_negative, lock_pairs
from app.services.units import cassette_mm

KINDS: dict[str, type[NamedItem]] = {
    "camera": Camera,
    "lens": Lens,
    "developer": Developer,
    "filter": Filter,
    "format": Format,
    "film": Film,
}


class UnknownNames(Exception):
    """Names used by the sheet that exist in no list. `unknown` maps a kind to its names."""

    def __init__(self, unknown: dict[str, list[str]]) -> None:
        self.unknown = unknown
        super().__init__(
            "Unknown names (add them to the sheet's lists or the reference screens): "
            + "; ".join(f"{kind}: {', '.join(names)}" for kind, names in unknown.items())
        )


class LoadError(Exception):
    """The sheet conflicts with data already in the database."""


@dataclass
class LoadReport:
    inserted: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def count(self, tab: str, inserted: bool) -> None:
        target = self.inserted if inserted else self.skipped
        target[tab] = target.get(tab, 0) + 1

    @property
    def total_inserted(self) -> int:
        return sum(self.inserted.values())


def fingerprint(tab: str, row: Mapping[str, str | None]) -> str:
    """A stable hash of a row's content (never its line number) within a tab."""
    payload = json.dumps([tab, sorted(row.items())], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _fields(row: object) -> dict[str, str | None]:
    """A row's content as text; a blank cell stays null so it differs from the text "None"."""
    assert is_dataclass(row)
    out: dict[str, str | None] = {}
    for f in fields(row):
        if f.name != "line":
            value = getattr(row, f.name)
            out[f.name] = None if value is None else str(value)
    return out


def _fold(name: str) -> str:
    return name.casefold()


def _names(sheet: ParsedSheet) -> dict[str, list[str]]:
    """Every name the sheet itself defines, per kind."""
    lists = sheet.lists
    return {
        "camera": lists.cameras,
        "lens": lists.lenses,
        "developer": lists.developers,
        "filter": lists.filters,
        "format": lists.formats,
        "film": [f.name for f in sheet.films],
    }


def _used(sheet: ParsedSheet) -> dict[str, list[str]]:
    """Every name the data rows refer to, per kind."""
    used: dict[str, list[str]] = {k: [] for k in KINDS}
    for r in sheet.tracker:
        used["camera"].append(r.camera)
        used["format"].append(r.format)
        used["film"].append(r.film)
        used["developer"].append(r.developer)
        if r.lens:
            used["lens"].append(r.lens)
        if r.filter:
            used["filter"].append(r.filter)
    for o in sheet.openings:
        used["film"].append(o.film)
        used["format"].append(o.format)
    for b in sheet.bulk:
        used["film"].append(b.film)
    for p in sheet.purchases:
        if p.film:
            used["film"].append(p.film)
        if p.format:
            used["format"].append(p.format)
    for d in sheet.dev_times:
        used["film"].append(d.film)
        used["developer"].append(d.developer)
    return used


async def _existing(session: AsyncSession) -> dict[str, dict[str, uuid.UUID]]:
    """Existing reference items per kind, keyed by case-folded name."""
    found: dict[str, dict[str, uuid.UUID]] = {}
    for kind, model in KINDS.items():
        rows = (await session.execute(select(model.name, model.id))).all()
        found[kind] = {_fold(str(name)): item_id for name, item_id in rows}
    return found


def check_names(sheet: ParsedSheet, existing: dict[str, dict[str, uuid.UUID]]) -> None:
    """Raise `UnknownNames` listing every name that is in neither the database nor the sheet."""
    defined = _names(sheet)
    unknown: dict[str, list[str]] = {}
    for kind, names in _used(sheet).items():
        known = set(existing[kind]) | {_fold(n) for n in defined[kind]}
        missing = sorted({n for n in names if _fold(n) not in known}, key=_fold)
        if missing:
            unknown[kind] = missing
    if unknown:
        raise UnknownNames(unknown)


class _Ledger:
    """Tracks which rows were imported before, and records the new ones."""

    def __init__(self, session: AsyncSession, actor: uuid.UUID, report: LoadReport) -> None:
        self.session = session
        self.actor = actor
        self.report = report
        self.done: dict[tuple[str, str, int], uuid.UUID | None] = {}

    async def load(self) -> None:
        rows = (
            await self.session.execute(
                select(
                    ImportLedger.tab,
                    ImportLedger.fingerprint,
                    ImportLedger.occurrence,
                    ImportLedger.record_id,
                )
            )
        ).all()
        self.done = {(t, f, o): rid for t, f, o, rid in rows}

    def keys(self, tab: str, rows: list[Any]) -> list[tuple[Any, str, int]]:
        """(row, fingerprint, occurrence) for each row, numbering identical rows 1, 2, ..."""
        seen: Counter[str] = Counter()
        out = []
        for row in rows:
            fp = fingerprint(tab, _fields(row) if is_dataclass(row) else {"name": str(row)})
            seen[fp] += 1
            out.append((row, fp, seen[fp]))
        return out

    def target(self, tab: str, fp: str, occurrence: int) -> uuid.UUID | None:
        """The record a previous run created for this row, if any."""
        return self.done.get((tab, fp, occurrence))

    def is_done(self, tab: str, fp: str, occurrence: int) -> bool:
        if (tab, fp, occurrence) in self.done:
            self.report.count(tab, False)
            return True
        return False

    def record(self, tab: str, fp: str, occurrence: int, record_id: uuid.UUID) -> None:
        self.session.add(
            ImportLedger(
                tab=tab,
                fingerprint=fp,
                occurrence=occurrence,
                record_id=record_id,
                created_by=self.actor,
                updated_by=self.actor,
            )
        )
        self.report.count(tab, True)


async def load_all(
    session: AsyncSession, sheet: ParsedSheet, actor_user_id: uuid.UUID, commit: bool = True
) -> LoadReport:
    """Import everything in one transaction. Raises `UnknownNames` (nothing written) or
    `LoadError`; any failure rolls the whole run back. With `commit=False` the work is flushed
    but left open, so the caller can check it (reconciliation) and then commit or roll back."""
    existing = await _existing(session)
    check_names(sheet, existing)  # before any write
    report = LoadReport()
    ledger = _Ledger(session, actor_user_id, report)
    try:
        await ledger.load()
        await _load(session, sheet, actor_user_id, existing, ledger)
        if commit:
            await session.commit()
        else:
            await session.flush()
    except BaseException:
        await session.rollback()
        raise
    return report


async def _reference(
    session: AsyncSession,
    sheet: ParsedSheet,
    actor: uuid.UUID,
    existing: dict[str, dict[str, uuid.UUID]],
    ledger: _Ledger,
) -> None:
    """Create the reference items the Lists and Films tabs define (those not already present)."""
    for kind, names in _names(sheet).items():
        tab = f"lists.{kind}" if kind != "film" else "films"
        rows: list[Any] = sheet.films if kind == "film" else list(names)
        for row, fp, occ in ledger.keys(tab, rows):
            name = row.name if kind == "film" else row
            if ledger.is_done(tab, fp, occ):
                # Renamed since the import? The recorded id still resolves the sheet's name.
                recorded = ledger.target(tab, fp, occ)
                if recorded is not None:
                    existing[kind].setdefault(_fold(name), recorded)
                continue
            item_id = existing[kind].get(_fold(name))
            if item_id is None:
                values: dict[str, Any] = {"name": name, "created_by": actor, "updated_by": actor}
                if kind == "film":
                    values.update(type=row.type, box_iso=row.box_iso)
                item = KINDS[kind](**values)
                session.add(item)
                await session.flush()
                item_id = item.id
                existing[kind][_fold(name)] = item_id
            ledger.record(tab, fp, occ, item_id)


async def _load(
    session: AsyncSession,
    sheet: ParsedSheet,
    actor: uuid.UUID,
    existing: dict[str, dict[str, uuid.UUID]],
    ledger: _Ledger,
) -> None:
    await _reference(session, sheet, actor, existing, ledger)
    ids = {kind: existing[kind] for kind in KINDS}

    def ref(kind: str, name: str) -> uuid.UUID:
        return ids[kind][_fold(name)]

    # Bulk spools first: purchases may load from them.
    spools: dict[str, BulkRoll] = {
        _fold(str(b.label)): b for b in (await session.execute(select(BulkRoll))).scalars()
    }
    by_id = {b.id: b for b in spools.values()}
    for row, fp, occ in ledger.keys("bulk", sheet.bulk):
        if ledger.is_done("bulk", fp, occ):
            # Renamed since the import? The recorded id still resolves the sheet's label.
            recorded = ledger.target("bulk", fp, occ)
            if recorded in by_id:
                spools.setdefault(_fold(row.label), by_id[recorded])
            continue
        if _fold(row.label) in spools:
            raise LoadError(f"Bulk roll '{row.label}' (line {row.line}) already exists.")
        spool = BulkRoll(
            label=row.label,
            film_id=ref("film", row.film),
            length_mm=row.length_mm,
            used_before_mm=row.used_before_mm,
            bought_on=row.bought_on,
            cost_pence=row.cost_pence,
            supplier=row.supplier,
            notes=row.notes,
            created_by=actor,
            updated_by=actor,
        )
        session.add(spool)
        await session.flush()
        spools[_fold(row.label)] = spool
        ledger.record("bulk", fp, occ, spool.id)

    # Lock every pair a counted write may lower before writing, so the snapshot is pre-write.
    candidates: set[Pair] = set()
    for r in sheet.tracker:
        if r.dev_date > OPENING_DATE:
            candidates.add((ref("film", r.film), ref("format", r.format)))
    for p in sheet.purchases:
        if p.kind == "given_away" and p.film and p.format:
            candidates.add((ref("film", p.film), ref("format", p.format)))
    before = await lock_pairs(session, candidates)

    counted: set[Pair] = set()
    for row, fp, occ in ledger.keys("tracker", sheet.tracker):
        if ledger.is_done("tracker", fp, occ):
            continue
        counts = row.dev_date > OPENING_DATE
        roll = Roll(
            dev_date=row.dev_date,
            camera_id=ref("camera", row.camera),
            lens_id=ref("lens", row.lens) if row.lens else None,
            format_id=ref("format", row.format),
            film_id=ref("film", row.film),
            ei=row.ei,
            developer_id=ref("developer", row.developer),
            dev_time_min=row.dev_time_min,
            filter_id=ref("filter", row.filter) if row.filter else None,
            subject=row.subject,
            notes=row.notes,
            source=row.source,
            counts_against_stock=counts,
            created_by=actor,
            updated_by=actor,
        )
        session.add(roll)
        await session.flush()
        if counts:
            counted.add((roll.film_id, roll.format_id))
        ledger.record("tracker", fp, occ, roll.id)

    for row, fp, occ in ledger.keys("openings", sheet.openings):
        if ledger.is_done("openings", fp, occ):
            continue
        movement = StockMovement(
            kind="opening",
            film_id=ref("film", row.film),
            format_id=ref("format", row.format),
            occurred_on=row.occurred_on,
            rolls=row.rolls,
            created_by=actor,
            updated_by=actor,
        )
        session.add(movement)
        await session.flush()
        ledger.record("openings", fp, occ, movement.id)

    settings = await get_settings(session)
    for row, fp, occ in ledger.keys("purchases", sheet.purchases):
        if ledger.is_done("purchases", fp, occ):
            continue
        values: dict[str, Any] = {
            "kind": row.kind,
            "occurred_on": row.occurred_on,
            "rolls": row.rolls,
            "notes": row.notes,
            "created_by": actor,
            "updated_by": actor,
        }
        if row.kind == "bulk_load":
            assert row.bulk_label is not None and row.exposures_per_cassette is not None
            source = spools.get(_fold(row.bulk_label))
            if source is None:
                raise LoadError(f"Line {row.line}: unknown bulk roll '{row.bulk_label}'.")
            values.update(
                film_id=source.film_id,
                format_id=ref("format", "35mm"),
                bulk_roll_id=source.id,
                exposures_per_cassette=row.exposures_per_cassette,
                metres_mm=row.rolls
                * cassette_mm(
                    settings.leader_mm, settings.frame_pitch_mm, row.exposures_per_cassette
                ),
            )
        else:
            assert row.film is not None and row.format is not None
            values.update(film_id=ref("film", row.film), format_id=ref("format", row.format))
            if row.kind == "purchase":
                values.update(cost_pence=row.cost_pence, supplier=row.supplier)
            if row.kind == "given_away":
                counted.add((values["film_id"], values["format_id"]))
        movement = StockMovement(**values)
        session.add(movement)
        await session.flush()
        ledger.record("purchases", fp, occ, movement.id)

    # Rolls after the opening date and given-away stock count, so they must not overdraw.
    if counted:
        await assert_non_negative(session, counted, before)
