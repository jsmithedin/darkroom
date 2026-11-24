"""MCP tools that change data. Each needs films:write and leaves an audit event.

There are deliberately no delete tools: removing records stays a deliberate act in the app.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.identity import WRITE, Principal
from app.mcp.context import EngineGetter, caller, resolve_ref, tool_session
from app.models.reference import RefKind
from app.schemas import reference as ref_schemas
from app.schemas.bulk import BulkRollIn, BulkRollOut, BulkRollUpdate
from app.schemas.rolls import RollIn, RollOut, RollUpdate
from app.schemas.stock import (
    AdjustmentIn,
    BulkLoadIn,
    GivenAwayIn,
    MovementOut,
    PurchaseIn,
)
from app.services import bulk as bulk_svc
from app.services import reference as ref_svc
from app.services import rolls as rolls_svc
from app.services import stock as stock_svc
from app.services.audit import record_audit

# Everything a service can refuse with becomes a tool error the model can read and act on.
REFUSALS = (
    stock_svc.InsufficientStockError,
    stock_svc.NotFoundError,
    stock_svc.InvalidMovementError,
    rolls_svc.NotFoundError,
    rolls_svc.InvalidReferenceError,
    bulk_svc.NotFoundError,
    bulk_svc.InvalidBulkRollError,
    bulk_svc.ConflictError,
    ref_svc.NotFoundError,
    ref_svc.DuplicateNameError,
    ValidationError,
)

Name = Annotated[str, Field(description="Name (any case) or id; see list_reference_data.")]
Notes = Annotated[str | None, Field(max_length=2000)]
NO_LENS = {"none", "n/a", "na"}


def _refusal_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    return str(exc)


async def _attempt[T](call: Callable[[], Awaitable[T]]) -> T:
    try:
        return await call()
    except REFUSALS as exc:
        raise ToolError(_refusal_text(exc)) from exc


async def _audit(
    db: AsyncSession,
    who: Principal,
    tool: str,
    entity_type: str,
    result: BaseModel,
    **extra: Any,
) -> None:
    summary = result.model_dump(mode="json") | extra
    entity_id = uuid.UUID(str(summary["id"])) if "id" in summary else None
    await record_audit(db, who, tool, entity_type, entity_id, summary)


async def _lens(db: AsyncSession, value: str | None) -> uuid.UUID | None:
    if value is None or value.strip().casefold() in NO_LENS:
        return None
    return await resolve_ref(db, RefKind.LENSES, value)


def register_write_tools(mcp: MCPServer, engine: EngineGetter) -> None:
    @mcp.tool()
    async def log_roll(
        dev_date: Annotated[date, Field(description="Date the roll was developed.")],
        camera: Name,
        film: Name,
        ei: Annotated[Decimal, Field(gt=0, description="Exposure index it was shot at.")],
        developer: Name,
        format: Annotated[str, Field(description="Format name or id.")] = "35mm",
        lens: Annotated[str | None, Field(description="Lens name, or 'none'.")] = None,
        dev_time_min: Annotated[Decimal | None, Field(gt=0, description="Minutes.")] = None,
        filter: Annotated[str | None, Field(description="Filter name or id.")] = None,
        subject: Annotated[str | None, Field(max_length=5000)] = None,
        notes: Annotated[str | None, Field(max_length=5000)] = None,
        source: Annotated[
            Literal["factory", "bulk"], Field(description="'bulk' if hand-rolled.")
        ] = "factory",
    ) -> RollOut:
        """Log a developed roll. Uses one roll of stock, and fails if none is recorded.

        If it fails for stock, tell the user and offer record_purchase or
        record_stock_adjustment rather than guessing.
        """
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> RollOut:
                body = RollIn(
                    dev_date=dev_date,
                    camera_id=await _need(db, RefKind.CAMERAS, camera),
                    lens_id=await _lens(db, lens),
                    format_id=await _need(db, RefKind.FORMATS, format),
                    film_id=await _need(db, RefKind.FILMS, film),
                    ei=ei,
                    developer_id=await _need(db, RefKind.DEVELOPERS, developer),
                    dev_time_min=dev_time_min,
                    filter_id=await resolve_ref(db, RefKind.FILTERS, filter),
                    subject=subject,
                    notes=notes,
                    source=source,
                )
                return RollOut.model_validate(await rolls_svc.create_roll(db, who, body))

            roll = await _attempt(run)
            await _audit(db, who, "log_roll", "roll", roll)
            return roll

    @mcp.tool()
    async def update_roll(
        roll_id: uuid.UUID,
        dev_date: date | None = None,
        camera: Name | None = None,
        film: Name | None = None,
        ei: Annotated[Decimal | None, Field(gt=0)] = None,
        developer: Name | None = None,
        format: str | None = None,
        lens: Annotated[str | None, Field(description="Lens name, or 'none' to clear.")] = None,
        dev_time_min: Annotated[Decimal | None, Field(gt=0)] = None,
        filter: str | None = None,
        subject: Annotated[str | None, Field(max_length=5000)] = None,
        notes: Annotated[str | None, Field(max_length=5000)] = None,
    ) -> RollOut:
        """Change fields of a logged roll. Only the fields you pass change."""
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> RollOut:
                changes: dict[str, Any] = {}
                for key, kind, value in (
                    ("camera_id", RefKind.CAMERAS, camera),
                    ("film_id", RefKind.FILMS, film),
                    ("developer_id", RefKind.DEVELOPERS, developer),
                    ("format_id", RefKind.FORMATS, format),
                    ("filter_id", RefKind.FILTERS, filter),
                ):
                    if value is not None:
                        changes[key] = await _need(db, kind, value)
                if lens is not None:
                    changes["lens_id"] = await _lens(db, lens)
                for key, plain in (
                    ("dev_date", dev_date),
                    ("ei", ei),
                    ("dev_time_min", dev_time_min),
                    ("subject", subject),
                    ("notes", notes),
                ):
                    if plain is not None:
                        changes[key] = plain
                if not changes:
                    raise ToolError("Nothing to change: pass at least one field.")
                updated = await rolls_svc.update_roll(db, who, roll_id, RollUpdate(**changes))
                return RollOut.model_validate(updated)

            roll = await _attempt(run)
            await _audit(db, who, "update_roll", "roll", roll)
            return roll

    @mcp.tool()
    async def record_purchase(
        film: Name,
        occurred_on: date,
        rolls: Annotated[int, Field(gt=0, le=10_000)],
        cost_pence: Annotated[int, Field(ge=0, description="Receipt total in pence.")],
        format: Annotated[str, Field(description="Format name or id.")] = "35mm",
        supplier: Annotated[str | None, Field(max_length=200)] = None,
        notes: Notes = None,
    ) -> MovementOut:
        """Record film bought: adds rolls to stock. Money is whole pence (£12.50 is 1250)."""
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> MovementOut:
                body = PurchaseIn(
                    kind="purchase",
                    film_id=await _need(db, RefKind.FILMS, film),
                    format_id=await _need(db, RefKind.FORMATS, format),
                    occurred_on=occurred_on,
                    rolls=rolls,
                    cost_pence=cost_pence,
                    supplier=supplier,
                    notes=notes,
                )
                return MovementOut.model_validate(await stock_svc.record_purchase(db, who, body))

            movement = await _attempt(run)
            await _audit(db, who, "record_purchase", "stock_movement", movement)
            return movement

    @mcp.tool()
    async def record_bulk_load(
        bulk_roll: Annotated[str, Field(description="Spool label or id; see get_bulk_rolls.")],
        occurred_on: date,
        rolls: Annotated[int, Field(gt=0, le=1_000, description="Cassettes loaded.")],
        exposures_per_cassette: Annotated[int, Field(gt=0, le=100)] = 36,
        notes: Notes = None,
    ) -> MovementOut:
        """Record cassettes loaded from a bulk spool: uses spool length and adds 35mm stock."""
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> MovementOut:
                body = BulkLoadIn(
                    kind="bulk_load",
                    bulk_roll_id=await _bulk_id(db, bulk_roll),
                    occurred_on=occurred_on,
                    rolls=rolls,
                    exposures_per_cassette=exposures_per_cassette,
                    notes=notes,
                )
                return MovementOut.model_validate(await stock_svc.record_bulk_load(db, who, body))

            movement = await _attempt(run)
            await _audit(db, who, "record_bulk_load", "stock_movement", movement)
            return movement

    @mcp.tool()
    async def record_given_away(
        film: Name,
        occurred_on: date,
        rolls: Annotated[int, Field(gt=0, le=10_000, description="How many rolls, positive.")],
        format: Annotated[str, Field(description="Format name or id.")] = "35mm",
        notes: Notes = None,
    ) -> MovementOut:
        """Record rolls given away or lost: removes them from stock. Fails if there are too few."""
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> MovementOut:
                body = GivenAwayIn(
                    kind="given_away",
                    film_id=await _need(db, RefKind.FILMS, film),
                    format_id=await _need(db, RefKind.FORMATS, format),
                    occurred_on=occurred_on,
                    rolls=-rolls,
                    notes=notes,
                )
                return MovementOut.model_validate(await stock_svc.record_given_away(db, who, body))

            movement = await _attempt(run)
            await _audit(db, who, "record_given_away", "stock_movement", movement)
            return movement

    @mcp.tool()
    async def record_stock_adjustment(
        film: Name,
        counted: Annotated[int, Field(ge=0, le=100_000, description="Rolls actually counted.")],
        occurred_on: date,
        format: Annotated[str, Field(description="Format name or id.")] = "35mm",
        notes: Notes = None,
    ) -> MovementOut:
        """Set stock for one film and format to a counted figure (a recount).

        The server works out the difference. Refused if the count equals the recorded stock.
        """
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> MovementOut:
                body = AdjustmentIn(
                    film_id=await _need(db, RefKind.FILMS, film),
                    format_id=await _need(db, RefKind.FORMATS, format),
                    counted=counted,
                    occurred_on=occurred_on,
                    notes=notes,
                )
                return MovementOut.model_validate(await stock_svc.record_adjustment(db, who, body))

            movement = await _attempt(run)
            await _audit(db, who, "record_stock_adjustment", "stock_movement", movement)
            return movement

    @mcp.tool()
    async def create_bulk_roll(
        label: Annotated[str, Field(min_length=1, max_length=100)],
        film: Name,
        length_mm: Annotated[int, Field(gt=0, le=1_000_000, description="Millimetres.")],
        cost_pence: Annotated[int | None, Field(ge=0)] = None,
        supplier: Annotated[str | None, Field(max_length=2000)] = None,
        bought_on: date | None = None,
        used_before_mm: Annotated[int, Field(ge=0, description="Used before tracking.")] = 0,
        notes: Notes = None,
    ) -> BulkRollOut:
        """Add a bulk film spool. Lengths are millimetres (30.5 m is 30500), money is pence."""
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> BulkRollOut:
                body = BulkRollIn(
                    label=label,
                    film_id=await _need(db, RefKind.FILMS, film),
                    length_mm=length_mm,
                    cost_pence=cost_pence,
                    supplier=supplier,
                    bought_on=bought_on,
                    used_before_mm=used_before_mm,
                    notes=notes,
                )
                return await bulk_svc.create_bulk_roll(db, who, body)

            spool = await _attempt(run)
            await _audit(db, who, "create_bulk_roll", "bulk_roll", spool)
            return spool

    @mcp.tool()
    async def update_bulk_roll(
        bulk_roll: Annotated[str, Field(description="Spool label or id.")],
        label: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
        length_mm: Annotated[int | None, Field(gt=0, le=1_000_000)] = None,
        cost_pence: Annotated[int | None, Field(ge=0)] = None,
        supplier: Annotated[str | None, Field(max_length=2000)] = None,
        bought_on: date | None = None,
        used_before_mm: Annotated[int | None, Field(ge=0)] = None,
        finished: Annotated[bool | None, Field(description="Mark the spool used up.")] = None,
        notes: Notes = None,
    ) -> BulkRollOut:
        """Change a bulk spool. Only the fields you pass change."""
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> BulkRollOut:
                given = {
                    "label": label,
                    "length_mm": length_mm,
                    "cost_pence": cost_pence,
                    "supplier": supplier,
                    "bought_on": bought_on,
                    "used_before_mm": used_before_mm,
                    "finished": finished,
                    "notes": notes,
                }
                changes = {k: v for k, v in given.items() if v is not None}
                if not changes:
                    raise ToolError("Nothing to change: pass at least one field.")
                return await bulk_svc.update_bulk_roll(
                    db, who, await _bulk_id(db, bulk_roll), BulkRollUpdate(**changes)
                )

            spool = await _attempt(run)
            await _audit(db, who, "update_bulk_roll", "bulk_roll", spool)
            return spool

    @mcp.tool()
    async def add_reference_item(
        kind: Annotated[RefKind, Field(description="What to add.")],
        name: Annotated[str, Field(min_length=1, max_length=100)],
        film_type: Annotated[
            Literal["bw", "colour", "slide"] | None, Field(description="Films only.")
        ] = None,
        box_iso: Annotated[int | None, Field(gt=0, description="Films only.")] = None,
        fixed_lens: Annotated[bool, Field(description="Cameras only.")] = False,
        notes: Annotated[str | None, Field(max_length=2000, description="Cameras only.")] = None,
    ) -> dict[str, Any]:
        """Add a camera, lens, developer, filter, film or format to the lists.

        Films need film_type and box_iso. Items can be archived in the app but never deleted.
        """
        who = caller(WRITE)
        async with tool_session(engine) as db:

            async def run() -> dict[str, Any]:
                data: BaseModel
                out: type[ref_schemas.ItemOut] = ref_schemas.ItemOut
                if kind is RefKind.FILMS:
                    if film_type is None or box_iso is None:
                        raise ToolError("A film needs film_type (bw, colour, slide) and box_iso.")
                    data = ref_schemas.FilmCreate(name=name, type=film_type, box_iso=box_iso)
                    out = ref_schemas.FilmOut
                elif kind is RefKind.CAMERAS:
                    data = ref_schemas.CameraCreate(name=name, fixed_lens=fixed_lens, notes=notes)
                    out = ref_schemas.CameraOut
                else:
                    data = ref_schemas.NamedCreate(name=name)
                item = await ref_svc.create_item(db, kind, data.model_dump(), who.user_id)
                return out.model_validate(item).model_dump(mode="json")

            created = await _attempt(run)
            await record_audit(
                db, who, "add_reference_item", kind.value, uuid.UUID(created["id"]), created
            )
            return created


async def _need(db: AsyncSession, kind: RefKind, value: str) -> uuid.UUID:
    found = await resolve_ref(db, kind, value)
    if found is None:
        raise ToolError(f"A {kind.value.rstrip('s')} is required.")
    return found


async def _bulk_id(db: AsyncSession, value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        pass
    wanted = value.strip().casefold()
    for spool in await bulk_svc.get_bulk_rolls(db, True):
        if spool.label.casefold() == wanted:
            return spool.id
    raise ToolError(f"No bulk spool labelled '{value}'. Use get_bulk_rolls.")
