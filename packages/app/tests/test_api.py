"""The API contract.

Two things are asserted here that matter more than the endpoints themselves:
a read endpoint returns exactly what the engine returns, and there is no
endpoint through which a derived value can be set.
"""

import os
import sys

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory, avs):
    db = tmp_path_factory.mktemp("api") / "qs.db"
    os.environ["QS_DB"] = str(db)
    for name in [m for m in sys.modules if m.startswith("qs_app.server")]:
        del sys.modules[name]

    from qs_app.store import Store
    Store(db).save(avs.model, avs.params)

    from qs_app import server
    server.state = server.State(db)
    return TestClient(server.app)


def test_headline_matches_the_workbook(client):
    h = client.get("/api/headline").json()
    assert h["flats"] == 278
    assert h["offices"] == 32
    assert h["floors"] == 37
    assert h["doors"] == 2178
    assert h["classification"]["2BHK"] == 143


def test_room_config_totals_are_derived(client):
    data = client.get("/api/room-config").json()
    assert len(data["floors"]) == 37
    flat_1b = next(u for u in data["unit_types"] if u["code"] == "Flat 1B")
    assert flat_1b["total"] == 18
    assert data["classification"]["1BHK"] == 28


def test_unit_type_areas(client):
    types = client.get("/api/unit-types").json()
    flat_1b = next(u for u in types if u["code"] == "Flat 1B")
    assert flat_1b["area_sqft"] == pytest.approx(757.35504, abs=1e-4)
    assert flat_1b["total_sqft"] == pytest.approx(13632.39072, abs=1e-3)


def test_rate_buildup_reaches_the_api(client):
    rates = client.get("/api/rates").json()
    flooring = next(r for r in rates
                    if r["description"] == "Flooring" and r["basic_rate"] == 45)
    assert flooring["overall_rate"] == pytest.approx(1340.118)
    assert flooring["derivation"]["rule"] == "area_with_wastage"


def test_a_derived_value_cannot_be_written(client):
    """There is no endpoint through which area_sqft or overall_rate can be set."""
    rooms = client.get("/api/unit-types/avs-ut-flat-1b-2bhk/rooms").json()["rooms"]
    r = client.put(f"/api/rooms/{rooms[0]['id']}", json={"area_sqft": 999})
    assert r.status_code == 400
    assert "not an input" in r.json()["detail"]

    rate_id = client.get("/api/rates").json()[0]["id"]
    r = client.put(f"/api/rates/{rate_id}", json={"overall_rate": 999})
    assert r.status_code == 400
    assert "derived" in r.json()["detail"]


def test_editing_one_count_moves_every_dependent_total(client):
    """The automation, end to end through the API."""
    config = client.get("/api/room-config").json()
    floor = next(f for f in config["floors"] if f["name"] == "7th Floor")
    unit = next(u for u in config["unit_types"] if u["code"] == "Flat 1B")
    before = client.get("/api/headline").json()

    r = client.put("/api/room-config/cell", json={
        "floor_id": floor["id"], "unit_type_id": unit["id"], "count": 3})
    after = r.json()["headline"]

    assert after["flats"] == before["flats"] + 3
    assert after["classification"]["2BHK"] == before["classification"]["2BHK"] + 3
    assert after["doors"] > before["doors"]
    assert after["carpet_area_sqft"] > before["carpet_area_sqft"]

    client.put("/api/room-config/cell", json={
        "floor_id": floor["id"], "unit_type_id": unit["id"], "count": 0})
    assert client.get("/api/headline").json()["flats"] == before["flats"]


def test_changing_a_parameter_moves_every_rate_built_on_it(client):
    rates = client.get("/api/rates").json()
    flooring = next(r for r in rates
                    if r["description"] == "Flooring" and r["basic_rate"] == 45)
    plaster = next(r for r in rates if r["method"] == "area_simple")

    client.put("/api/parameters/factor_sqm_to_sqft", json={"value": 11.0})
    after = client.get("/api/rates").json()
    assert next(r for r in after if r["id"] == flooring["id"])["overall_rate"] == \
        pytest.approx((45 * 1.1 + 75) * 11.0)
    assert next(r for r in after if r["id"] == plaster["id"])["overall_rate"] != \
        pytest.approx(plaster["overall_rate"])

    client.put("/api/parameters/factor_sqm_to_sqft", json={"value": 10.764})


def test_every_write_is_audited(client):
    before = len(client.get("/api/audit").json())
    rate_id = client.get("/api/rates").json()[0]["id"]
    client.put(f"/api/rates/{rate_id}", json={"basic_rate": 123})
    entries = client.get("/api/audit").json()
    assert len(entries) > before
    assert entries[0]["field"] == "basic_rate"
    assert entries[0]["new_value"] == "123"


# --------------------------------------------------------------------------
# One number, one answer -- the views must not drift apart
# --------------------------------------------------------------------------

def test_the_room_view_and_the_takeoff_measure_the_same_wall(client):
    """Wall area depends on the floor, so both screens must resolve it the same.

    The take-off folds a unit type over the floors it sits on. The Unit Types
    screen shows one room at a time. If that screen fell back to the project
    default height while the take-off used the floor's, the two would report
    different walls for one room -- exactly the disagreement this platform
    exists to remove.
    """
    types = client.get("/api/unit-types").json()
    unit = next(t for t in types if t["rooms"] and t["count"])

    detail = client.get(f"/api/unit-types/{unit['id']}/rooms").json()
    assert detail["heights"], "a unit type with a count sits on at least one floor"
    assert detail["floor_height_m"] == max(
        detail["heights"], key=lambda h: h["count"])["height_m"]

    room = next(r for r in detail["rooms"] if r["perimeter_m"])
    wall = next(q for q in room["quantities"] if q["rule"] == "wall_finish")

    lines = client.get(f"/api/takeoff?unit_type_id={unit['id']}").json()["lines"]
    matching = [l for l in lines
                if l["room_id"] == room["id"] and l["rule"] == "wall_finish"
                and l["gross"]]
    assert matching, "the take-off measures this room's wall too"
    assert wall["gross"] == pytest.approx(
        max(matching, key=lambda l: l["unit_count"])["gross"], rel=1e-9)


def test_the_wall_derivation_names_where_its_height_came_from(client):
    """A QS should be able to see that 4.2 came from the floor, not a default."""
    types = client.get("/api/unit-types").json()
    unit = next(t for t in types if t["rooms"] and t["count"])
    detail = client.get(f"/api/unit-types/{unit['id']}/rooms").json()
    room = next(r for r in detail["rooms"] if r["perimeter_m"])
    wall = next(q for q in room["quantities"] if q["rule"] == "wall_finish")

    names = {i["name"]: i for i in wall["gross_derivation"]["inputs"]}
    assert "floor_to_floor_ht" in names
    assert names["floor_to_floor_ht"]["source"] in {"floor", "room", "parameter"}
    assert "slab_allowance_m" in names
