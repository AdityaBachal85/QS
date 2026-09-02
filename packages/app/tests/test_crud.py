"""Adding, renaming and deleting -- and the guards around deleting.

The workbook carries eight live ``#REF!`` errors (C-10): deletions that broke
references and that nobody noticed, because the cells sit far to the right of a
168-row sheet. These tests are the reason that cannot happen here.
"""

import pytest

from qs_app import crud
from qs_app.crud import CrudError
from qs_engine.model import RoomCategory
from qs_engine.rules.unit_area import unit_type_area_sqft, unit_type_total_sqft


@pytest.fixture
def project(avs):
    """A fresh copy per test, since these mutate the model."""
    import copy
    return copy.deepcopy(avs.model), avs.params


def unit_type(model, code):
    return next(u for u in model.unit_types if u.code == code)


# -- adding ---------------------------------------------------------------

def test_add_a_floor(project):
    model, _ = project
    before = len(model.floors)
    floor = crud.create(model, "floors", {"name": "38th Floor",
                                          "floor_to_floor_ht": 3.1})
    assert len(model.floors) == before + 1
    assert floor.name == "38th Floor"
    assert floor.seq == max(f.seq for f in model.floors)


def test_add_a_unit_type_and_it_joins_the_classification_split(project):
    model, _ = project
    before = model.counts_by_classification().get("4BHK", 0)
    unit = crud.create(model, "unit-types", {"code": "Villa A",
                                             "classification": "4BHK"})
    from qs_engine.model import FloorUnitMix
    model.floor_unit_mix.append(FloorUnitMix(
        id="m", floor_id=model.floors[0].id, unit_type_id=unit.id, count=6))
    assert model.counts_by_classification()["4BHK"] == before + 6


def test_a_unit_type_can_have_four_toilets(project):
    """The shape the user asked for, built through the API rather than imported."""
    model, params = project
    unit = crud.create(model, "unit-types", {"code": "Villa B",
                                             "classification": "4BHK"})
    toilet = next(t for t in model.room_types
                  if t.category is RoomCategory.TOILET)
    for n in range(1, 5):
        crud.create(model, "rooms", {
            "unit_type_id": unit.id, "room_type_id": toilet.id,
            "label": f"Toilet {n}", "carpet_area_sqm": 3.5, "perimeter_m": 7.6})

    rooms = model.rooms_of(unit.id)
    assert len(rooms) == 4
    assert [r.label for r in rooms] == ["Toilet 1", "Toilet 2", "Toilet 3", "Toilet 4"]
    assert unit_type_area_sqft(unit.id, model, params).value == \
        pytest.approx(4 * 3.5 * params["factor_sqm_to_sqft"])


def test_a_new_room_computes_quantities_immediately(project):
    """No code change, no configuration -- it measures as soon as it exists."""
    from qs_engine.rules.room_qty import compute_room_quantity
    model, params = project
    unit = crud.create(model, "unit-types", {"code": "Villa C"})
    room = crud.create(model, "rooms", {
        "unit_type_id": unit.id, "room_type_id": model.room_types[0].id,
        "label": "Living", "carpet_area_sqm": 30.0, "perimeter_m": 22.0})

    floor = compute_room_quantity(room, "floor_area", model, params)
    skirting = compute_room_quantity(room, "skirting", model, params)
    assert floor.net.value == pytest.approx(30.0)
    assert skirting.net.value == pytest.approx(22.0)
    assert skirting.net.unit.code == "RM"


# -- renaming -------------------------------------------------------------

def test_rename_a_unit_type(project):
    model, _ = project
    unit = unit_type(model, "Flat 1A")
    crud.update(model, "unit-types", unit.id, {"code": "Flat 1A — Studio"})
    assert model.unit_type(unit.id).code == "Flat 1A — Studio"


def test_a_derived_value_cannot_be_set_through_crud(project):
    model, _ = project
    room = model.unit_type_rooms[0]
    with pytest.raises(CrudError, match="not an input"):
        crud.update(model, "rooms", room.id, {"area_sqft": 999})


# -- deleting -------------------------------------------------------------

def test_deleting_a_room_type_in_use_is_refused_and_names_what_uses_it(project):
    model, _ = project
    in_use = model.room_type(model.unit_type_rooms[0].room_type_id)
    with pytest.raises(CrudError, match="rooms"):
        crud.delete(model, "room-types", in_use.id)
    assert in_use in model.room_types


def test_deleting_an_opening_type_in_use_is_refused(project):
    model, _ = project
    used = model.opening_type(model.room_openings[0].opening_type_id)
    with pytest.raises(CrudError, match="openings in rooms"):
        crud.delete(model, "opening-types", used.id)


def test_deleting_a_rate_still_priced_on_is_refused(project):
    model, _ = project
    priced = next(s.rate_item_id for s in model.room_finish_specs if s.rate_item_id)
    with pytest.raises(CrudError, match="finish schedule rows"):
        crud.delete(model, "rate-items", priced)


def test_deleting_a_unit_type_takes_its_rooms_and_their_openings(project):
    model, _ = project
    unit = unit_type(model, "Flat 5A")
    room_ids = {r.id for r in model.rooms_of(unit.id)}
    opening_ids = {o.id for o in model.room_openings
                   if o.unit_type_room_id in room_ids}
    assert room_ids and opening_ids

    removed = crud.delete(model, "unit-types", unit.id)

    assert removed["unit type"] == 1
    assert removed["room"] == len(room_ids)
    assert removed["opening"] == len(opening_ids)
    assert not any(r.id in room_ids for r in model.unit_type_rooms)
    assert not any(o.id in opening_ids for o in model.room_openings)
    assert not any(m.unit_type_id == unit.id for m in model.floor_unit_mix)


def test_deleting_never_renumbers_the_others(project):
    """seq orders rows; it is an attribute, not a position."""
    model, _ = project
    victim = next(f for f in model.floors if f.seq == 3)
    others = {f.id: f.seq for f in model.floors if f.id != victim.id}

    crud.delete(model, "floors", victim.id)

    assert {f.id: f.seq for f in model.floors} == others
    assert 3 not in {f.seq for f in model.floors}


def test_blockers_can_be_asked_before_deleting(project):
    """So the UI can warn rather than surprise."""
    model, _ = project
    in_use = model.room_type(model.unit_type_rooms[0].room_type_id)
    assert crud.blockers(model, "room-types", in_use.id)
    spare = crud.create(model, "room-types", {"name": "Powder Room"})
    assert crud.blockers(model, "room-types", spare.id) == []
    crud.delete(model, "room-types", spare.id)
