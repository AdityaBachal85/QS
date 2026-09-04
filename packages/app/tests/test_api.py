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


# --------------------------------------------------------------------------
# Serving -- a pull has to reach the screen
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/", "/static/app.js", "/static/style.css",
    "/static/screens/finish-totals.js", "/static/screens/openings.js",
])
def test_the_ui_always_revalidates(client, path):
    """The regression that made a pulled build invisible.

    Starlette sends `etag` and `last-modified` but no `Cache-Control`, and the
    module URLs carry no version, so a browser applies heuristic freshness and
    reuses `app.js` for hours. A route added to the new `app.js` is then never
    registered and its screen comes up empty.

    What matters is that the browser may never reuse a copy without asking, so
    either directive is correct: `no-store` forbids keeping it, `no-cache`
    keeps it but forces revalidation.
    """
    response = client.get(path)
    assert response.status_code == 200
    directive = response.headers.get("cache-control", "")
    assert "no-store" in directive or "no-cache" in directive, \
        f"{path} may be served from cache without revalidating: {directive!r}"


def test_static_assets_revalidate_cheaply(client):
    """A conditional request returns 304 rather than the file again.

    `no-store` also guaranteed freshness, but forbade keeping the file at all,
    so every load re-downloaded all fifteen modules.
    """
    first = client.get("/static/app.js")
    etag = first.headers.get("etag")
    assert etag, "no etag to revalidate against"

    again = client.get("/static/app.js", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert not again.content


def test_the_running_build_is_reported(client):
    """"Did my pull take effect?" should be one glance, not a source read."""
    version = client.get("/api/version").json()
    assert set(version) >= {"commit", "committed_at", "branch"}
    if version["commit"] != "unknown":
        assert 6 <= len(version["commit"]) <= 12


# --------------------------------------------------------------------------
# Seeding -- the data has to be this build's too
# --------------------------------------------------------------------------

def test_seeding_over_an_existing_database_reimports_and_backs_it_up(tmp_path, avs):
    """Door and window rates are attached at import time.

    A database written by an older build has opening types with no rate at all,
    so every opening prices at nothing and the schedule totals zero -- which
    reads as a broken screen rather than as stale data.
    """
    from qs_app.seed import seed
    from qs_app.store import Store

    db = tmp_path / "qs.db"
    seed(db, avs.workbook.path)
    first = Store(db).load("avs")

    # Strip the rates the way a pre-B3.5 database would have them.
    stripped = Store(db).load("avs")
    for opening in stripped.opening_types:
        opening.rate_item_id = None
    Store(db).save(stripped)
    assert not any(o.rate_item_id for o in Store(db).load("avs").opening_types)

    seed(db, avs.workbook.path)

    after = Store(db).load("avs")
    assert len(after.opening_types) == len(first.opening_types)
    assert all(o.rate_item_id for o in after.opening_types), \
        "a re-import must restore the rates an older build never wrote"
    assert (tmp_path / "qs.db.bak").exists(), "the previous database is kept"


def test_keep_leaves_an_existing_database_alone(tmp_path, avs):
    from qs_app.seed import seed
    from qs_app.store import Store

    db = tmp_path / "qs.db"
    seed(db, avs.workbook.path)

    marked = Store(db).load("avs")
    marked.project.name = "edited by hand"
    Store(db).save(marked)

    seed(db, avs.workbook.path, keep=True)
    assert Store(db).load("avs").project.name == "edited by hand"


def test_a_seeded_database_prices_every_opening(client):
    """The exact state that made Doors & Windows read zero."""
    costs = client.get("/api/opening-totals").json()
    assert costs["total"] > 0
    priced = [l for l in costs["lines"] if l["rate"]]
    assert len(priced) == len(costs["lines"]), "every type carries a rate"


# -- the kitchen counters ---------------------------------------------------

def test_the_counters_tab_shows_only_rooms_priced_off_a_counter(client):
    """A unit type with no kitchen does not grow an empty card."""
    types = client.get("/api/unit-types").json()
    flat = next(t for t in types if t["code"] == "Flat 7")
    data = client.get(
        f"/api/unit-types/{flat['id']}/kitchen-platforms").json()
    assert len(data["rooms"]) == 1
    row = data["rooms"][0]
    assert row["room_type"] == "Kitchen"
    assert set(row["priced_for"]) >= {"kitchen_platform", "service_platform"}


def test_the_tab_computes_both_dado_areas_beside_the_entries(client):
    """(main x above) + (service x above), from the engine, not the browser."""
    types = client.get("/api/unit-types").json()
    flat = next(t for t in types if t["code"] == "Flat 7")
    row = client.get(
        f"/api/unit-types/{flat['id']}/kitchen-platforms").json()["rooms"][0]

    assert row["dado_above"] == pytest.approx(
        (row["main_platform_m"] + row["service_platform_m"]) * row["dado_above_m"])
    assert row["dado_above_derivation"]["expression"] == "(3.52 x 1.5) + (2.62 x 1.5)"
    assert row["dado_below_derivation"]["expression"] == "(3.52 x 0.9) + (2.62 x 0.9)"


def test_typing_a_counter_run_moves_the_cost_with_no_linking_step(client):
    types = client.get("/api/unit-types").json()
    flat = next(t for t in types if t["code"] == "Flat 7")
    row = client.get(
        f"/api/unit-types/{flat['id']}/kitchen-platforms").json()["rooms"][0]

    def kitchen_costs():
        rooms = client.get(f"/api/unit-types/{flat['id']}/rooms").json()["rooms"]
        room = next(r for r in rooms if r["id"] == row["unit_type_room_id"])
        return {c["finish"]: c for c in room["costs"]}

    before = kitchen_costs()
    original = row["main_platform_m"]
    client.patch(f"/api/collections/kitchen-platforms/{row['id']}",
                     json={"main_platform_m": original + 1.0})
    after = kitchen_costs()

    assert after["Kitchen Platform"]["net"] == pytest.approx(original + 1.0)
    # The dado above and below both move by the extra run times their heights.
    assert after["Dado"]["net"] - before["Dado"]["net"] == pytest.approx(
        1.0 * row["dado_above_m"])
    assert (after["Dado Below Kitchen Platform"]["net"]
            - before["Dado Below Kitchen Platform"]["net"]) == pytest.approx(
        1.0 * row["dado_below_m"])
    # And the plaster falls by exactly the extra tiling: you do not plaster
    # behind the tiles.
    walls_before = sum(c["net"] for f, c in before.items() if f == "Wall finishes plaster")
    walls_after = sum(c["net"] for f, c in after.items() if f == "Wall finishes plaster")
    assert walls_after < walls_before

    client.patch(f"/api/collections/kitchen-platforms/{row['id']}",
                     json={"main_platform_m": original})


def test_a_room_cannot_carry_two_sets_of_counters(client):
    """A room has the counters it has; two rows would be two answers."""
    types = client.get("/api/unit-types").json()
    flat = next(t for t in types if t["code"] == "Flat 7")
    row = client.get(
        f"/api/unit-types/{flat['id']}/kitchen-platforms").json()["rooms"][0]
    refused = client.post("/api/collections/kitchen-platforms",
                              json={"unit_type_room_id": row["unit_type_room_id"]})
    assert refused.status_code == 400
    assert "already has its counters" in refused.json()["detail"]


def test_a_room_with_no_counters_reports_rather_than_showing_zero(client):
    """The three office Pantries whose size matches no take-off block."""
    types = client.get("/api/unit-types").json()
    office = next(t for t in types if t["code"] == "Office 2")
    row = client.get(
        f"/api/unit-types/{office['id']}/kitchen-platforms").json()["rooms"][0]
    assert row["id"] is None
    assert row["dado_above"] is None and row["dado_below"] is None
    assert "no counters entered" in row["message"]


def test_the_counters_survive_a_round_trip_through_the_store(client):
    from qs_app import server

    saved = server.state.store.load("avs")
    assert len(saved.kitchen_platforms) == 17
    assert all(p.main_platform_m or p.service_platform_m
               for p in saved.kitchen_platforms)


# -- every figure carries its working --------------------------------------

def test_every_opening_line_can_explain_its_count_and_quantity(client):
    """C-18: the count is a fold over the rooms, and says which rooms."""
    data = client.get("/api/openings").json()
    for line in data["doors"] + data["windows"]:
        assert line["count_derivation"], f"{line['code']} cannot explain its count"
        working = line["count_derivation"]
        assert working["inputs"], f"{line['code']} names no contributing room"
        assert sum(i["value"] for i in working["inputs"]) == pytest.approx(
            line["count"]), f"{line['code']}'s inputs do not add to its count"
        assert line["quantity_derivation"]
        assert line["area_derivation"]["expression"] == (
            f"{line['width_m']:g} x {line['height_m']:g}")


def test_every_priced_opening_can_explain_its_rate_and_amount(client):
    costs = client.get("/api/opening-totals").json()
    priced = [l for l in costs["lines"] if l["status"] == "priced"]
    assert priced
    for line in priced:
        assert line["rate_derivation"], f"{line['code']} cannot explain its rate"
        assert line["amount_derivation"]
        # The amount's working must reproduce the amount, not merely mention it.
        values = [i["value"] for i in line["amount_derivation"]["inputs"]]
        assert len(values) == 2
        assert values[0] * values[1] == pytest.approx(line["amount"], rel=1e-6)


def test_an_opening_band_explains_which_types_make_it_up(client):
    costs = client.get("/api/opening-totals").json()
    for band in costs["bands"]:
        assert band["count_derivation"] and band["amount_derivation"]
        counts = band["count_derivation"]["inputs"]
        assert sum(i["value"] for i in counts) == pytest.approx(band["count"])
        amounts = band["amount_derivation"]["inputs"]
        assert sum(i["value"] for i in amounts) == pytest.approx(
            band["amount"], rel=1e-6)


def test_every_summary_section_explains_what_it_folds(client):
    """C-38: a section is a filter, and its working says what matched."""
    s = client.get("/api/summary").json()
    for section in s["sections"]:
        assert section["derivation"], f"{section['name']} has no working"
        inputs = section["derivation"]["inputs"]
        assert sum(i["value"] for i in inputs) == pytest.approx(
            section["amount"], rel=1e-6), (
            f"{section['name']}'s working does not add to its amount")
        assert "filter" in section["derivation"]["note"]


def test_every_floor_explains_how_many_units_it_holds(client):
    config = client.get("/api/room-config").json()
    for floor in config["floors"]:
        working = floor["row_total_derivation"]
        assert working
        assert sum(i["value"] for i in working["inputs"]) == pytest.approx(
            floor["row_total"])


def test_a_room_type_mapping_says_what_its_worth_is_made_of(client):
    rows = client.get("/api/room-type-mapping").json()["mappings"]
    priced = [r for r in rows if r["amount"]]
    assert priced
    for row in priced:
        assert row["worth_from"], f"{row['name']} cannot say where its money is"
        assert sum(u["amount"] for u in row["worth_from"]) == pytest.approx(
            row["amount"], rel=1e-6)


def test_every_group_on_a_totals_screen_can_be_opened(client):
    """Not just the one fold that happened to have a handler."""
    for route, folds in (("/api/finish-totals",
                          ("by_finish", "by_room_type", "by_unit_type", "matrix")),
                         ("/api/takeoff", ("by_finish", "by_unit_type"))):
        payload = client.get(route).json()
        assert payload["contributors"]
        for fold in folds:
            for group in payload[fold]:
                if not (group["amount"] or group["quantity"]):
                    continue
                rows = payload["contributors"].get(group["key"])
                assert rows, f"{route} {fold} {group['label']} has no breakdown"
                assert sum(r["amount"] for r in rows) == pytest.approx(
                    group["amount"], rel=1e-6)


def test_a_reconciliation_line_carries_the_delta_it_predicted(client):
    """An EXPLAINED line must be able to show the size it was predicted to be."""
    r = client.get("/api/reconciliation").json()
    explained = [l for l in r["lines"] if l["status"] == "EXPLAINED"]
    assert explained
    for line in explained:
        assert line["expected_delta"] is not None
        assert line["difference"] == pytest.approx(line["expected_delta"], abs=0.01)


# -- the dado line: measured, and nothing changed --------------------------

def test_the_dado_report_changes_no_number(client):
    """C3.4 is a measurement, not an edit. Asking must not move anything."""
    before = client.get("/api/finish-totals").json()["total"]
    report = client.get("/api/dado-basis").json()
    assert report["rows"]
    after = client.get("/api/finish-totals").json()["total"]
    assert after == pytest.approx(before), "reporting moved the take-off"
    assert report["total_now"] == pytest.approx(before)


def test_the_dado_and_the_wall_should_partition_the_height(client):
    """The finding itself: today they overlap, and the workbook's do not."""
    rows = client.get("/api/dado-basis").json()["rows"]
    toilets = [r for r in rows if "Toilet" in r["room_type"] or r["room_type"] == "WC"]
    assert toilets
    for row in toilets:
        # The workbook's two bands add to about the room's own height. Ours add
        # to far more, which is the same strip charged twice. The tolerance is
        # loose because a unit type spanning two floor heights is averaged into
        # one figure for this table -- the point is the shape, not the decimal.
        workbook = row["dado_workbook"] + row["wall_workbook"]
        assert 2.9 <= workbook <= 3.7, (
            f"{row['room_type']} does not partition in the workbook: {workbook:.2f}")
        assert row["dado_now"] + row["wall_now"] > workbook + 1.0, (
            f"{row['room_type']} already partitions — this report is stale")


def test_the_report_leaves_counter_measured_rooms_alone(client):
    """A kitchen's dado runs along its counters and is already right."""
    rows = client.get("/api/dado-basis").json()["rows"]
    named = {r["room_type"] for r in rows}
    assert "Kitchen" not in named and "Pantry" not in named


def test_the_report_says_what_the_change_would_be_worth(client):
    d = client.get("/api/dado-basis").json()
    assert d["total_partitioned"] - d["total_now"] == pytest.approx(d["moves_by"])
    assert d["moves_by"] == pytest.approx(sum(r["money"] for r in d["rows"]),
                                          rel=0.02)
    assert abs(d["gap_partitioned"]) < abs(d["gap_now"]), (
        "the proposal should move the take-off toward the workbook")


def test_the_build_stamp_says_whether_it_is_the_current_one(client):
    """A hash on its own says nothing.

    The Kitchen platforms tab read as "missing" for a week because the running
    checkout was behind and the only clue was a seven-character hash in the
    corner. The version route now carries how far behind it is, so the screen
    can say so instead of leaving somebody to guess.
    """
    v = client.get("/api/version").json()
    assert "behind" in v, "the stamp cannot say whether it is current"
    assert isinstance(v["behind"], int) and v["behind"] >= 0
    assert "commit" in v and "committed_at" in v


def test_being_behind_is_only_claimed_when_it_is_certain(client):
    """Wrong in the safe direction: silence when it cannot tell.

    The count is read from refs already on disk so it works with no network,
    which means it can be stale. Reporting 0 when there is something new is the
    right way to be wrong -- it never nags, and when it speaks it is certain.
    """
    from qs_app.server import commits_behind

    assert commits_behind() >= 0          # never negative, never raises


# -- the Internal Finishes sheet, rebuilt ----------------------------------

def test_the_sheet_is_laid_out_the_way_the_workbook_lays_it_out(client):
    """Unit type, then room block, then the finish rows under it."""
    d = client.get("/api/internal-finishes").json()
    assert d["unit_types"]
    unit = next(u for u in d["unit_types"] if u["code"] == "Flat 7")
    assert unit["units"] > 0
    room = next(r for r in unit["rooms"] if r["label"] == "Kitchen")
    assert room["carpet_area_sqm"] > 0 and room["perimeter_m"] > 0
    assert {l["finish"] for l in room["lines"]} >= {
        "Flooring", "Dado", "Kitchen Platform", "Service Platform"}


def test_every_room_carries_the_sheets_own_rate_per_square_foot(client, avs):
    """Column M: SUM(L)/C/10.764 -- the room's cost over its carpet, in sq ft."""
    d = client.get("/api/internal-finishes").json()
    factor = avs.params["factor_sqm_to_sqft"]
    for unit in d["unit_types"]:
        for room in unit["rooms"]:
            if not room["rate_per_sqft"]:
                continue
            expected = room["amount_per_unit"] / (room["carpet_area_sqm"] * factor)
            assert room["rate_per_sqft"] == pytest.approx(expected, rel=1e-9)


def test_the_summary_is_a_fold_over_the_blocks_above_it(client):
    """Not a second reading of them, so the two cannot drift apart.

    The workbook's own summary is a SUMIF over a bounded range, which is how
    F2040 ends up counting row 2010 twice (C-15).
    """
    d = client.get("/api/internal-finishes").json()
    assert d["summary"]
    assert sum(e["amount"] for e in d["summary"]) == pytest.approx(
        d["total"], rel=1e-9)

    from_blocks = sum(r["total_amount"]
                      for u in d["unit_types"] for r in u["rooms"])
    assert from_blocks == pytest.approx(d["total"], rel=1e-9), (
        "the room blocks and the total disagree")


def test_it_agrees_with_the_takeoff_it_is_a_view_of(client):
    """One set of lines, shown two ways -- never two sets."""
    sheet = client.get("/api/internal-finishes").json()
    totals = client.get("/api/finish-totals").json()
    assert sheet["total"] == pytest.approx(totals["total"], rel=1e-9)


def test_measured_but_unpriced_lines_appear_rather_than_vanish(client):
    """C-11: work presented as absent is how Rs 65.5 lakh disappeared."""
    d = client.get("/api/internal-finishes").json()
    assert d["unpriced"] > 0
    shown = [l for u in d["unit_types"] for r in u["rooms"] for l in r["lines"]
             if l["status"] != "priced"]
    assert len(shown) == d["unpriced"]
    for line in shown:
        assert line["message"], "an unpriced line must say why"
