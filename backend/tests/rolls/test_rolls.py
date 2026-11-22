import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Roll


@pytest.fixture
async def gear(authed: AsyncClient) -> dict[str, str]:
    """One of each reference item, as ids."""

    async def make(kind: str, body: dict[str, Any]) -> str:
        resp = await authed.post(f"/api/{kind}", json=body)
        assert resp.status_code == 201, resp.text
        return str(resp.json()["id"])

    formats = {f["name"]: f["id"] for f in (await authed.get("/api/formats")).json()}
    return {
        "camera": await make("cameras", {"name": "Nikon FM2"}),
        "camera2": await make("cameras", {"name": "Olympus XA", "fixed_lens": True}),
        "lens": await make("lenses", {"name": "50mm f/1.8"}),
        "film": await make("films", {"name": "Tri-X", "type": "bw", "box_iso": 400}),
        "film2": await make("films", {"name": "Portra", "type": "colour", "box_iso": 160}),
        "developer": await make("developers", {"name": "HC-110"}),
        "developer2": await make("developers", {"name": "Rodinal"}),
        "filter": await make("filters", {"name": "Yellow"}),
        "format35": formats["35mm"],
        "format120": formats["120"],
    }


def roll(g: dict[str, str], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "dev_date": "2026-11-01",
        "camera_id": g["camera"],
        "lens_id": g["lens"],
        "format_id": g["format35"],
        "film_id": g["film"],
        "ei": 400,
        "developer_id": g["developer"],
    }
    body.update(over)
    return body


async def add(authed: AsyncClient, g: dict[str, str], **over: Any) -> dict[str, Any]:
    resp = await authed.post("/api/rolls", json=roll(g, **over))
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def ids(authed: AsyncClient, **params: Any) -> list[str]:
    resp = await authed.get("/api/rolls", params=params)
    assert resp.status_code == 200, resp.text
    return [r["id"] for r in resp.json()["items"]]


async def test_roll_out_derived_fields_not_stored(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    created = await add(authed, gear, dev_date="2026-03-15", ei=800)
    assert created["year"] == 2026
    assert created["month"] == 3
    assert created["film_type"] == "bw"
    assert created["box_iso"] == 400
    assert created["stops_vs_box"] == "+1"
    assert created["film"]["name"] == "Tri-X"
    assert created["camera"]["name"] == "Nikon FM2"
    assert created["source"] == "factory"
    assert created["counts_against_stock"] is True
    # none of the derived values is a column
    columns = {c.name for c in Roll.__table__.columns}
    assert not columns & {"year", "month", "film_type", "box_iso", "stops_vs_box"}


async def test_stops_follow_the_film_not_a_stored_value(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    created = await add(authed, gear, ei=400)
    assert created["stops_vs_box"] == "0"
    # changing the film's box speed would change it; here swap the roll to a 160 film
    patched = await authed.patch(f"/api/rolls/{created['id']}", json={"film_id": gear["film2"]})
    assert patched.json()["box_iso"] == 160
    assert patched.json()["stops_vs_box"] == "+1.3"


async def test_ei_decimal_roundtrip(authed: AsyncClient, gear: dict[str, str]) -> None:
    for sent, expected in [(200.5, 200.5), (400, 400), ("1600.25", 1600.25), (12.5, 12.5)]:
        created = await add(authed, gear, ei=sent)
        assert created["ei"] == expected
        fetched = (await authed.get(f"/api/rolls/{created['id']}")).json()
        assert fetched["ei"] == expected


@pytest.mark.parametrize("ei", [0, -400, 1.234, 10_000_000, "fast"])
async def test_ei_validation(authed: AsyncClient, gear: dict[str, str], ei: object) -> None:
    resp = await authed.post("/api/rolls", json=roll(gear, ei=ei))
    assert resp.status_code == 422


@pytest.mark.parametrize("dev_time", [0, -1, 1.234, 1000])
async def test_dev_time_validation(
    authed: AsyncClient, gear: dict[str, str], dev_time: object
) -> None:
    resp = await authed.post("/api/rolls", json=roll(gear, dev_time_min=dev_time))
    assert resp.status_code == 422


async def test_dev_time_optional_and_decimal(authed: AsyncClient, gear: dict[str, str]) -> None:
    assert (await add(authed, gear))["dev_time_min"] is None
    assert (await add(authed, gear, dev_time_min=9.75))["dev_time_min"] == 9.75


async def test_null_lens_means_na(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await add(authed, gear, camera_id=gear["camera2"], lens_id=None)
    assert created["lens"] is None
    assert (await authed.get(f"/api/rolls/{created['id']}")).json()["lens"] is None
    # also fine when the field is omitted entirely
    body = roll(gear, camera_id=gear["camera2"])
    del body["lens_id"]
    assert (await authed.post("/api/rolls", json=body)).json()["lens"] is None


async def test_filters_combine(authed: AsyncClient, gear: dict[str, str]) -> None:
    a = await add(authed, gear, dev_date="2026-01-10")
    b = await add(
        authed, gear, dev_date="2026-02-10", film_id=gear["film2"], camera_id=gear["camera2"]
    )
    c = await add(authed, gear, dev_date="2026-03-10", developer_id=gear["developer2"])
    d = await add(authed, gear, dev_date="2026-04-10", source="bulk")

    assert await ids(authed) == [d["id"], c["id"], b["id"], a["id"]]  # newest first
    assert await ids(authed, film=gear["film2"]) == [b["id"]]
    assert await ids(authed, camera=gear["camera"]) == [d["id"], c["id"], a["id"]]
    assert await ids(authed, developer=gear["developer2"]) == [c["id"]]
    assert await ids(authed, source="bulk") == [d["id"]]
    assert await ids(authed, **{"from": "2026-02-01", "to": "2026-03-10"}) == [c["id"], b["id"]]
    # combined filters narrow, they do not widen
    assert await ids(authed, camera=gear["camera"], **{"from": "2026-02-01"}) == [d["id"], c["id"]]
    assert await ids(authed, camera=gear["camera"], film=gear["film2"]) == []
    assert await ids(authed, camera=gear["camera"], source="factory", **{"to": "2026-03-31"}) == [
        c["id"],
        a["id"],
    ]


async def test_text_search_hits_subject_and_notes(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    sub = await add(authed, gear, subject="Harbour at dawn")
    note = await add(authed, gear, notes="Pushed one stop because of HARBOUR fog")
    other = await add(authed, gear, subject="Portraits", notes="Studio")
    assert set(await ids(authed, q="harbour")) == {sub["id"], note["id"]}
    assert await ids(authed, q="studio") == [other["id"]]
    assert await ids(authed, q="nothing like this") == []
    # LIKE wildcards in the search text are literal
    assert await ids(authed, q="%") == []
    assert await ids(authed, q="_") == []
    # blank search means no search
    assert len(await ids(authed, q="  ")) == 3


async def test_pagination(authed: AsyncClient, gear: dict[str, str]) -> None:
    for day in range(1, 6):
        await add(authed, gear, dev_date=f"2026-05-0{day}")
    page = (await authed.get("/api/rolls", params={"limit": 2, "offset": 2})).json()
    assert page["total"] == 5
    assert (page["limit"], page["offset"]) == (2, 2)
    assert [r["dev_date"] for r in page["items"]] == ["2026-05-03", "2026-05-02"]
    assert (await authed.get("/api/rolls", params={"limit": 0})).status_code == 422
    assert (await authed.get("/api/rolls", params={"limit": 500})).status_code == 422


async def test_last_roll_returns_most_recent_by_dev_date(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    older_entered_last = await add(authed, gear, dev_date="2026-01-01", lens_id=None)
    newest = await add(authed, gear, dev_date="2026-06-01", format_id=gear["format120"])
    await add(authed, gear, dev_date="2026-03-01", camera_id=gear["camera2"])  # other camera
    resp = await authed.get(f"/api/cameras/{gear['camera']}/last-roll")
    assert resp.status_code == 200
    assert resp.json()["id"] == newest["id"]
    assert resp.json()["format"]["name"] == "120"
    assert older_entered_last["id"] != newest["id"]


async def test_last_roll_404s(authed: AsyncClient, gear: dict[str, str]) -> None:
    no_rolls = await authed.get(f"/api/cameras/{gear['camera']}/last-roll")
    assert no_rolls.status_code == 404
    assert "yet" in no_rolls.json()["detail"]
    unknown = await authed.get(f"/api/cameras/{uuid.uuid4()}/last-roll")
    assert unknown.status_code == 404


async def test_patch_changes_only_sent_fields_and_can_clear(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    created = await add(authed, gear, subject="Keep me", notes="Clear me", filter_id=gear["filter"])
    resp = await authed.patch(
        f"/api/rolls/{created['id']}", json={"notes": None, "filter_id": None, "ei": 800}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == "Keep me"
    assert body["notes"] is None
    assert body["filter"] is None
    assert body["ei"] == 800
    assert body["camera"]["id"] == gear["camera"]


@pytest.mark.parametrize(
    "field", ["camera_id", "film_id", "ei", "dev_date", "counts_against_stock"]
)
async def test_patch_cannot_null_required_fields(
    authed: AsyncClient, gear: dict[str, str], field: str
) -> None:
    created = await add(authed, gear)
    resp = await authed.patch(f"/api/rolls/{created['id']}", json={field: None})
    assert resp.status_code == 422


async def test_unknown_reference_422(authed: AsyncClient, gear: dict[str, str]) -> None:
    resp = await authed.post("/api/rolls", json=roll(gear, camera_id=str(uuid.uuid4())))
    assert resp.status_code == 422
    assert "Unknown camera" in resp.json()["detail"]


async def test_archived_reference_cannot_be_newly_chosen_but_old_rolls_keep_it(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    created = await add(authed, gear, subject="before")
    await authed.post(f"/api/cameras/{gear['camera']}/archive")

    new = await authed.post("/api/rolls", json=roll(gear))
    assert new.status_code == 422
    assert "archived" in new.json()["detail"]

    # the old roll still reads and can be edited while keeping its archived camera
    assert (await authed.get(f"/api/rolls/{created['id']}")).json()["camera"]["name"] == "Nikon FM2"
    edited = await authed.patch(f"/api/rolls/{created['id']}", json={"subject": "after"})
    assert edited.status_code == 200
    same = await authed.patch(
        f"/api/rolls/{created['id']}", json={"camera_id": gear["camera"], "notes": "x"}
    )
    assert same.status_code == 200
    # but it cannot be switched to a different archived item
    await authed.post(f"/api/lenses/{gear['lens']}/archive")
    moved = await authed.patch(f"/api/rolls/{created['id']}", json={"lens_id": gear["lens"]})
    assert moved.status_code == 200  # unchanged value, so still allowed
    other = (await authed.post("/api/lenses", json={"name": "85mm"})).json()
    await authed.post(f"/api/lenses/{other['id']}/archive")
    refused = await authed.patch(f"/api/rolls/{created['id']}", json={"lens_id": other["id"]})
    assert refused.status_code == 422


async def test_delete_roll(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await add(authed, gear)
    assert (await authed.delete(f"/api/rolls/{created['id']}")).status_code == 204
    assert (await authed.get(f"/api/rolls/{created['id']}")).status_code == 404
    assert (await authed.delete(f"/api/rolls/{created['id']}")).status_code == 404


async def test_unknown_roll_404(authed: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await authed.get(f"/api/rolls/{missing}")).status_code == 404
    assert (await authed.patch(f"/api/rolls/{missing}", json={"notes": "x"})).status_code == 404


async def test_attribution_and_defaults(
    authed: AsyncClient, gear: dict[str, str], engine: AsyncEngine
) -> None:
    await add(authed, gear)
    async with engine.connect() as conn:
        row = (await conn.execute(text("select created_by, updated_by from rolls"))).one()
        user = (await conn.execute(text("select id from users"))).scalar_one()
    assert row.created_by == user == row.updated_by


async def test_source_and_counts_flag(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await add(authed, gear, source="bulk", counts_against_stock=False)
    assert created["source"] == "bulk"
    assert created["counts_against_stock"] is False
    resp = await authed.post("/api/rolls", json=roll(gear, source="mystery"))
    assert resp.status_code == 422


async def test_scopes(
    authed: AsyncClient,
    gear: dict[str, str],
    bearer_client: Callable[..., Awaitable[AsyncClient]],
) -> None:
    created = await add(authed, gear)
    reader = await bearer_client("films:read")
    async with reader:
        assert (await reader.get("/api/rolls")).status_code == 200
        assert (await reader.get(f"/api/rolls/{created['id']}")).status_code == 200
        assert (await reader.get(f"/api/cameras/{gear['camera']}/last-roll")).status_code == 200
        assert (await reader.post("/api/rolls", json=roll(gear))).status_code == 403
        assert (
            await reader.patch(f"/api/rolls/{created['id']}", json={"notes": "x"})
        ).status_code == 403
        assert (await reader.delete(f"/api/rolls/{created['id']}")).status_code == 403


async def test_unauthenticated_401(client: AsyncClient) -> None:
    assert (await client.get("/api/rolls")).status_code == 401
    assert (await client.get(f"/api/cameras/{uuid.uuid4()}/last-roll")).status_code == 401


async def test_unknown_query_filters_validated(authed: AsyncClient) -> None:
    assert (await authed.get("/api/rolls", params={"from": "not-a-date"})).status_code == 422
    assert (await authed.get("/api/rolls", params={"source": "mystery"})).status_code == 422
    assert (await authed.get("/api/rolls", params={"film": "nope"})).status_code == 422
