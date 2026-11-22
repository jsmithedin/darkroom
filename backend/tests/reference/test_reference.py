import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

KINDS = ["cameras", "lenses", "developers", "filters", "films", "formats"]


def payload(kind: str, name: str = "Thing") -> dict[str, object]:
    if kind == "films":
        return {"name": name, "type": "bw", "box_iso": 400}
    return {"name": name}


async def test_formats_seeded(authed: AsyncClient, engine: AsyncEngine) -> None:
    resp = await authed.get("/api/formats")
    assert resp.status_code == 200
    assert {f["name"] for f in resp.json()} == {"35mm", "120", "110"}
    async with engine.connect() as conn:
        row = (
            await conn.execute(text("select leader_mm, frame_pitch_mm, timezone from settings"))
        ).one()
    assert tuple(row) == (250, 38, "Europe/London")


@pytest.mark.parametrize("kind", [k for k in KINDS])
async def test_create_list_update_roundtrip(authed: AsyncClient, kind: str) -> None:
    created = await authed.post(f"/api/{kind}", json=payload(kind, "Alpha"))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Alpha"
    assert body["archived_at"] is None

    names = [i["name"] for i in (await authed.get(f"/api/{kind}")).json()]
    assert "Alpha" in names

    patched = await authed.patch(f"/api/{kind}/{body['id']}", json={"name": "Beta"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Beta"


@pytest.mark.parametrize("kind", KINDS)
async def test_duplicate_name_409(authed: AsyncClient, kind: str) -> None:
    assert (await authed.post(f"/api/{kind}", json=payload(kind, "Same"))).status_code == 201
    for name in ("Same", "same", "  SAME  "):  # names are case-insensitive and trimmed
        resp = await authed.post(f"/api/{kind}", json=payload(kind, name))
        assert resp.status_code == 409, name
        assert "already exists" in resp.json()["detail"]


async def test_rename_to_existing_name_409(authed: AsyncClient) -> None:
    await authed.post("/api/lenses", json={"name": "50mm"})
    other = (await authed.post("/api/lenses", json={"name": "85mm"})).json()
    resp = await authed.patch(f"/api/lenses/{other['id']}", json={"name": "50MM"})
    assert resp.status_code == 409
    # renaming to its own name (or just recasing it) is fine
    assert (
        await authed.patch(f"/api/lenses/{other['id']}", json={"name": "85MM"})
    ).status_code == 200


async def test_duplicate_of_archived_item_says_so(authed: AsyncClient) -> None:
    item = (await authed.post("/api/developers", json={"name": "HC-110"})).json()
    await authed.post(f"/api/developers/{item['id']}/archive")
    resp = await authed.post("/api/developers", json={"name": "HC-110"})
    assert resp.status_code == 409
    assert "archived" in resp.json()["detail"]


@pytest.mark.parametrize("kind", KINDS)
async def test_archived_hidden_by_default_and_shown_with_include_archived(
    authed: AsyncClient, kind: str
) -> None:
    item = (await authed.post(f"/api/{kind}", json=payload(kind, "Old"))).json()
    archived = await authed.post(f"/api/{kind}/{item['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None

    default = [i["id"] for i in (await authed.get(f"/api/{kind}")).json()]
    assert item["id"] not in default
    with_archived = (await authed.get(f"/api/{kind}", params={"include_archived": "true"})).json()
    assert item["id"] in [i["id"] for i in with_archived]

    restored = await authed.post(f"/api/{kind}/{item['id']}/unarchive")
    assert restored.json()["archived_at"] is None
    assert item["id"] in [i["id"] for i in (await authed.get(f"/api/{kind}")).json()]


async def test_archive_is_idempotent(authed: AsyncClient) -> None:
    item = (await authed.post("/api/filters", json={"name": "Red"})).json()
    first = (await authed.post(f"/api/filters/{item['id']}/archive")).json()
    second = (await authed.post(f"/api/filters/{item['id']}/archive")).json()
    assert first["archived_at"] == second["archived_at"]


@pytest.mark.parametrize("box_iso", [0, -100, 1.5, "fast"])
async def test_film_box_iso_must_be_positive(authed: AsyncClient, box_iso: object) -> None:
    resp = await authed.post("/api/films", json={"name": "F", "type": "bw", "box_iso": box_iso})
    assert resp.status_code == 422


async def test_film_box_iso_must_be_positive_on_update(authed: AsyncClient) -> None:
    film = (await authed.post("/api/films", json=payload("films", "Tri-X"))).json()
    resp = await authed.patch(f"/api/films/{film['id']}", json={"box_iso": 0})
    assert resp.status_code == 422


async def test_film_type_validated(authed: AsyncClient) -> None:
    resp = await authed.post("/api/films", json={"name": "F", "type": "infrared", "box_iso": 100})
    assert resp.status_code == 422
    ok = await authed.post("/api/films", json={"name": "Ektar", "type": "colour", "box_iso": 100})
    assert ok.json()["type"] == "colour"


async def test_camera_fields(authed: AsyncClient) -> None:
    resp = await authed.post(
        "/api/cameras", json={"name": "Olympus XA", "fixed_lens": True, "notes": "Zone focus"}
    )
    assert resp.json()["fixed_lens"] is True
    patched = await authed.patch(f"/api/cameras/{resp.json()['id']}", json={"notes": None})
    assert patched.json()["notes"] is None
    assert patched.json()["fixed_lens"] is True  # untouched fields stay


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_name_validation(authed: AsyncClient, name: str) -> None:
    assert (await authed.post("/api/lenses", json={"name": name})).status_code == 422


async def test_unknown_fields_rejected(authed: AsyncClient) -> None:
    resp = await authed.post(
        "/api/lenses", json={"name": "x", "archived_at": "2020-01-01T00:00:00Z"}
    )
    assert resp.status_code == 422


async def test_unknown_id_404(authed: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await authed.patch(f"/api/lenses/{missing}", json={"name": "x"})).status_code == 404
    assert (await authed.post(f"/api/lenses/{missing}/archive")).status_code == 404
    assert (await authed.post(f"/api/lenses/{missing}/unarchive")).status_code == 404


async def test_attribution_recorded(authed: AsyncClient, engine: AsyncEngine) -> None:
    await authed.post("/api/lenses", json={"name": "35mm f/2"})
    async with engine.connect() as conn:
        row = (await conn.execute(text("select created_by, updated_by from lenses"))).one()
        user = (await conn.execute(text("select id from users"))).scalar_one()
    assert row.created_by == user == row.updated_by


async def test_unauthenticated_401(client: AsyncClient) -> None:
    assert (await client.get("/api/cameras")).status_code == 401


async def test_write_requires_films_write_scope(bearer_client) -> None:  # type: ignore[no-untyped-def]
    reader = await bearer_client("films:read")
    writer = await bearer_client("films:write")
    async with reader, writer:
        assert (await reader.get("/api/cameras")).status_code == 200
        assert (await reader.get("/api/formats")).status_code == 200
        created = await reader.post("/api/cameras", json={"name": "Nikon F"})
        assert created.status_code == 403
        assert "insufficient_scope" in created.headers["www-authenticate"]

        made = await writer.post("/api/cameras", json={"name": "Nikon F"})
        assert made.status_code == 201
        item_id = made.json()["id"]
        assert (await writer.get("/api/cameras")).status_code == 200  # write implies read
        for method, url, body in [
            ("PATCH", f"/api/cameras/{item_id}", {"name": "x"}),
            ("POST", f"/api/cameras/{item_id}/archive", None),
            ("POST", f"/api/cameras/{item_id}/unarchive", None),
        ]:
            resp = await reader.request(method, url, json=body)
            assert resp.status_code == 403, url
