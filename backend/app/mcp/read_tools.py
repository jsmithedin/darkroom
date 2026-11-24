"""Read-only MCP tools. Each is a thin adapter over a service and needs films:read."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.auth.identity import READ
from app.mcp.context import EngineGetter, caller, resolve_ref, tool_session
from app.models.reference import RefKind
from app.schemas import reference as ref_schemas
from app.schemas.bulk import BulkRollOut
from app.schemas.devtimes import DevTimeGroup
from app.schemas.rolls import RollOut, RollPage
from app.schemas.stats import Stats
from app.schemas.stock import FilmRef, FormatRef, StockRowOut
from app.services import bulk as bulk_svc
from app.services import devtimes as devtimes_svc
from app.services import reference as ref_svc
from app.services import rolls as rolls_svc
from app.services import stats as stats_svc
from app.services import stock as stock_svc
from app.services.settings import get_settings

OUT_BY_KIND: dict[RefKind, type[ref_schemas.ItemOut]] = {
    RefKind.CAMERAS: ref_schemas.CameraOut,
    RefKind.FILMS: ref_schemas.FilmOut,
}


def register_read_tools(mcp: MCPServer, engine: EngineGetter) -> None:
    @mcp.tool()
    async def list_rolls(
        date_from: Annotated[date | None, Field(description="Earliest development date.")] = None,
        date_to: Annotated[date | None, Field(description="Latest development date.")] = None,
        film: Annotated[str | None, Field(description="Film name or id.")] = None,
        camera: Annotated[str | None, Field(description="Camera name or id.")] = None,
        developer: Annotated[str | None, Field(description="Developer name or id.")] = None,
        source: Annotated[
            Literal["factory", "bulk"] | None,
            Field(description="'bulk' for hand-rolled cassettes, 'factory' for boxed film."),
        ] = None,
        q: Annotated[
            str | None, Field(max_length=200, description="Text to find in subject or notes.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Page size.")] = 50,
    ) -> RollPage:
        """List developed rolls, newest development date first, with optional filters.

        Each roll includes camera, lens, film, developer, EI, development time and the stops
        over or under the film's box ISO. `total` counts all matches, not just this page.
        """
        caller(READ)
        async with tool_session(engine) as db:
            filters = rolls_svc.RollFilters(
                date_from,
                date_to,
                await resolve_ref(db, RefKind.FILMS, film),
                await resolve_ref(db, RefKind.CAMERAS, camera),
                await resolve_ref(db, RefKind.DEVELOPERS, developer),
                source,
                q,
            )
            rows, total = await rolls_svc.list_rolls(db, filters, rolls_svc.Page(limit, 0))
            return RollPage(
                items=[RollOut.model_validate(r) for r in rows],
                total=total,
                limit=limit,
                offset=0,
            )

    @mcp.tool()
    async def get_stock() -> list[StockRowOut]:
        """Unexposed film in the freezer: rolls on hand per film and format.

        Only counts cassettes and boxes, not bulk film still on a spool (see get_bulk_rolls).
        Rows with zero rolls are left out.
        """
        caller(READ)
        async with tool_session(engine) as db:
            rows = await stock_svc.get_stock(db, False)
            return [
                StockRowOut(
                    film=FilmRef(id=r.film_id, name=r.film_name, type=r.film_type),
                    format=FormatRef(id=r.format_id, name=r.format_name),
                    rolls=r.rolls,
                )
                for r in rows
            ]

    @mcp.tool()
    async def get_bulk_rolls() -> list[BulkRollOut]:
        """Bulk film spools with length used and left, cassettes loaded, exposures left and cost.

        Lengths are millimetres and money is pence, as exact integers.
        """
        caller(READ)
        async with tool_session(engine) as db:
            return await bulk_svc.get_bulk_rolls(db, True)

    @mcp.tool()
    async def get_stats(
        year: Annotated[
            int | None, Field(ge=1900, le=2200, description="Defaults to the current year.")
        ] = None,
    ) -> Stats:
        """Roll counts by month, year-to-date comparison and breakdowns for one year."""
        caller(READ)
        async with tool_session(engine) as db:
            settings = await get_settings(db)
            today = stats_svc.london_today(datetime.now(UTC), settings.timezone)
            return await stats_svc.get_stats(db, today.year if year is None else year, today)

    @mcp.tool()
    async def get_dev_times(
        film: Annotated[str | None, Field(description="Film name or id.")] = None,
        ei: Annotated[
            Decimal | None, Field(description="Exposure index the film was shot at.")
        ] = None,
        developer: Annotated[str | None, Field(description="Developer name or id.")] = None,
    ) -> list[DevTimeGroup]:
        """Development times used before, grouped by film, EI and developer, newest first.

        Use it to choose a time for a roll. A hand-entered reference time may be attached.
        """
        caller(READ)
        async with tool_session(engine) as db:
            return await devtimes_svc.grouped_dev_times(
                db,
                await resolve_ref(db, RefKind.FILMS, film),
                ei,
                await resolve_ref(db, RefKind.DEVELOPERS, developer),
            )

    @mcp.tool()
    async def list_reference_data(
        kind: Annotated[
            RefKind, Field(description="cameras, lenses, developers, filters, films or formats.")
        ],
        include_archived: Annotated[bool, Field(description="Include retired items.")] = False,
    ) -> list[dict[str, Any]]:
        """List the names and ids of cameras, lenses, developers, filters, films or formats."""
        caller(READ)
        out = OUT_BY_KIND.get(kind, ref_schemas.ItemOut)
        async with tool_session(engine) as db:
            items = await ref_svc.list_items(db, kind, include_archived)
            return [out.model_validate(i).model_dump(mode="json") for i in items]
