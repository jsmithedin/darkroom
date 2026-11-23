from typing import Any

from httpx import AsyncClient

from tests.support import roll_body


async def log(authed: AsyncClient, g: dict[str, str], **over: Any) -> dict[str, Any]:
    body = roll_body(g, counts_against_stock=False, **over)
    resp = await authed.post("/api/rolls", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def groups(authed: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    resp = await authed.get("/api/dev-times", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def make_ref(authed: AsyncClient, g: dict[str, str], **over: Any) -> Any:
    body = {"film_id": g["film"], "ei": 400, "developer_id": g["developer"], "minutes": 9.5}
    return await authed.post("/api/dev-time-refs", json={**body, **over})


async def test_groups_by_film_ei_developer(authed: AsyncClient, gear: dict[str, str]) -> None:
    await log(authed, gear, dev_time_min=8)
    await log(authed, gear, dev_time_min=9)
    await log(authed, gear, ei=800, dev_time_min=11)
    await log(authed, gear, developer_id=gear["developer2"], dev_time_min=7)
    await log(authed, gear, film_id=gear["film2"], dev_time_min=6)
    found = await groups(authed)
    shape = [(g["film"]["name"], g["ei"], g["developer"]["name"], len(g["entries"])) for g in found]
    assert shape == [
        ("Portra", 400, "HC-110", 1),
        ("Tri-X", 400, "HC-110", 2),
        ("Tri-X", 400, "Rodinal", 1),
        ("Tri-X", 800, "HC-110", 1),
    ]


async def test_newest_first(authed: AsyncClient, gear: dict[str, str]) -> None:
    await log(authed, gear, dev_date="2026-01-01", dev_time_min=8)
    await log(authed, gear, dev_date="2026-03-01", dev_time_min=9)
    await log(authed, gear, dev_date="2026-02-01", dev_time_min=10)
    (group,) = await groups(authed)
    assert [e["dev_date"] for e in group["entries"]] == ["2026-03-01", "2026-02-01", "2026-01-01"]
    assert [e["minutes"] for e in group["entries"]] == [9, 10, 8]


async def test_null_times_excluded(authed: AsyncClient, gear: dict[str, str]) -> None:
    await log(authed, gear)  # no development time
    assert await groups(authed) == []
    await log(authed, gear, dev_time_min=8)
    (group,) = await groups(authed)
    assert len(group["entries"]) == 1


async def test_reference_shown_with_logged_times_and_alone(
    authed: AsyncClient, gear: dict[str, str]
) -> None:
    await log(authed, gear, dev_time_min=8)
    assert (await make_ref(authed, gear)).status_code == 201
    assert (await make_ref(authed, gear, ei=1600, minutes=14)).status_code == 201
    found = await groups(authed)
    assert [(g["ei"], len(g["entries"]), g["reference"] is not None) for g in found] == [
        (400, 1, True),
        (1600, 0, True),
    ]
    assert found[0]["reference"]["minutes"] == 9.5


async def test_ref_unique_conflict_409(authed: AsyncClient, gear: dict[str, str]) -> None:
    assert (await make_ref(authed, gear)).status_code == 201
    again = await make_ref(authed, gear, minutes=10)
    assert again.status_code == 409
    other = await make_ref(authed, gear, ei=800)
    assert other.status_code == 201
    clash = await authed.patch(f"/api/dev-time-refs/{other.json()['id']}", json={"ei": 400})
    assert clash.status_code == 409


async def test_filters(authed: AsyncClient, gear: dict[str, str]) -> None:
    await log(authed, gear, dev_time_min=8)
    await log(authed, gear, ei=800, dev_time_min=11)
    await log(authed, gear, developer_id=gear["developer2"], dev_time_min=7)
    await log(authed, gear, film_id=gear["film2"], dev_time_min=6)
    assert len(await groups(authed, film=gear["film2"])) == 1
    assert len(await groups(authed, ei=800)) == 1
    assert len(await groups(authed, developer=gear["developer2"])) == 1
    both = await groups(authed, film=gear["film"], developer=gear["developer"])
    assert [g["ei"] for g in both] == [400, 800]


async def test_ref_crud_and_validation(authed: AsyncClient, gear: dict[str, str]) -> None:
    created = await make_ref(authed, gear, notes="Stand 1+50")
    assert created.status_code == 201
    ref = created.json()
    assert ref["film"]["name"] == "Tri-X" and ref["developer"]["name"] == "HC-110"
    listed = (await authed.get("/api/dev-time-refs")).json()
    assert [r["id"] for r in listed] == [ref["id"]]
    patched = await authed.patch(
        f"/api/dev-time-refs/{ref['id']}", json={"minutes": 10.25, "notes": None}
    )
    assert patched.json()["minutes"] == 10.25 and patched.json()["notes"] is None
    assert (
        await authed.patch(f"/api/dev-time-refs/{ref['id']}", json={"minutes": None})
    ).status_code == 422
    assert (await make_ref(authed, gear, minutes=0)).status_code == 422
    assert (
        await make_ref(authed, gear, film_id="00000000-0000-0000-0000-000000000000")
    ).status_code == 422
    assert (await authed.delete(f"/api/dev-time-refs/{ref['id']}")).status_code == 204
    assert (await authed.delete(f"/api/dev-time-refs/{ref['id']}")).status_code == 404
    assert (await authed.get("/api/dev-time-refs")).json() == []


async def test_scopes(bearer_client: Any, gear: dict[str, str]) -> None:
    reader = await bearer_client("films:read")
    assert (await reader.get("/api/dev-times")).status_code == 200
    assert (await reader.get("/api/dev-time-refs")).status_code == 200
    body = {"film_id": gear["film"], "ei": 400, "developer_id": gear["developer"], "minutes": 9}
    assert (await reader.post("/api/dev-time-refs", json=body)).status_code == 403
    writer = await bearer_client("films:write")
    assert (await writer.post("/api/dev-time-refs", json=body)).status_code == 201
