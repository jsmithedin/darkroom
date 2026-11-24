import csv
import io
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base
from app.services.export import EXPORT_TABLES, UnknownTableError, export_table
from tests.support import roll_body


def parse(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


@pytest.mark.parametrize("table", EXPORT_TABLES)
async def test_every_domain_table_exports(
    authed: AsyncClient, gear: dict[str, str], table: str
) -> None:
    resp = await authed.get(f"/api/export/{table}.csv")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert f"darkroom-{table}.csv" in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "private, no-store"
    assert parse(resp.text)


@pytest.mark.parametrize("table", EXPORT_TABLES)
async def test_header_row_matches_columns(db_session: AsyncSession, table: str) -> None:
    chunks = [chunk async for chunk in export_table(db_session, table)]
    header = parse(chunks[0])[0]
    assert header == [column.name for column in Base.metadata.tables[table].columns]


async def test_rows_are_exported_with_their_values(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    created = await authed.post(
        "/api/rolls",
        json=roll_body(gear, counts_against_stock=False, notes="=HYPERLINK(1)", subject="a, b"),
    )
    assert created.status_code == 201, created.text
    rows = parse((await authed.get("/api/export/rolls.csv")).text)
    header, record = rows[0], rows[1]
    cell = dict(zip(header, record, strict=True))
    assert cell["id"] == created.json()["id"]
    assert cell["notes"] == "'=HYPERLINK(1)"  # kept inert in a spreadsheet
    assert cell["subject"] == "a, b"  # commas are quoted, not split
    assert cell["counts_against_stock"] == "false"
    assert cell["lens_id"] != "None"


async def test_numbers_and_empty_values_are_not_mangled(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    resp = await authed.post(
        "/api/stock-movements",
        json={
            "kind": "purchase",
            "film_id": gear["film"],
            "format_id": gear["format35"],
            "occurred_on": "2026-11-01",
            "rolls": 5,
            "cost_pence": 2500,
        },
    )
    assert resp.status_code == 201, resp.text
    rows = parse((await authed.get("/api/export/stock_movements.csv")).text)
    cell = dict(zip(rows[0], rows[1], strict=True))
    assert (cell["rolls"], cell["cost_pence"], cell["supplier"], cell["counted_to"]) == (
        "5",
        "2500",
        "",
        "",
    )


@pytest.mark.parametrize(
    "table",
    [
        "sessions",
        "personal_access_tokens",
        "oauth_clients",
        "oauth_codes",
        "oauth_tokens",
        "users",
        "import_ledger",
        "alembic_version",
        "stock_levels",
    ],
)
async def test_secret_tables_not_exportable(authed: AsyncClient, table: str) -> None:
    assert (await authed.get(f"/api/export/{table}.csv")).status_code == 404


async def test_secret_columns_never_appear_in_the_allowlist() -> None:
    for table in EXPORT_TABLES:
        for column in Base.metadata.tables[table].columns:
            assert "hash" not in column.name and "secret" not in column.name


async def test_unknown_table_404(authed: AsyncClient, db_session: AsyncSession) -> None:
    assert (await authed.get("/api/export/nope.csv")).status_code == 404
    with pytest.raises(UnknownTableError):
        async for _ in export_table(db_session, "nope"):
            pass


async def test_listing_and_auth(
    authed: AsyncClient, bearer_client: Callable[..., Awaitable[AsyncClient]]
) -> None:
    assert (await authed.get("/api/export")).json() == list(EXPORT_TABLES)
    anonymous = AsyncClient(
        transport=authed._transport,  # type: ignore[attr-defined]
        base_url=str(authed.base_url),
    )
    assert (await anonymous.get("/api/export/rolls.csv")).status_code == 401
    assert (await anonymous.get("/api/export")).status_code == 401
    await anonymous.aclose()
    reader = await bearer_client("films:read")
    assert (await reader.get("/api/export/rolls.csv")).status_code == 200
    await reader.aclose()


async def test_full_width_formula_prefixes_are_neutralised(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    resp = await authed.post(
        "/api/rolls",
        json=roll_body(gear, counts_against_stock=False, notes="＝1+1", subject="＋cmd"),
    )
    assert resp.status_code == 201, resp.text
    rows = parse((await authed.get("/api/export/rolls.csv")).text)
    cell = dict(zip(rows[0], rows[1], strict=True))
    assert cell["notes"] == "'＝1+1"
    assert cell["subject"] == "'＋cmd"


async def test_openapi_declares_csv(authed: AsyncClient) -> None:
    spec = (await authed.get("/api/openapi.json")).json()
    ok = spec["paths"]["/api/export/{table}.csv"]["get"]["responses"]["200"]
    assert "text/csv" in ok["content"]
