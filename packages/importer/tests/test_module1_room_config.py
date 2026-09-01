"""Module 1 gate -- Room Config."""

import pytest

from conftest import unit_type
from qs_engine.model import FloorUnitMix, UnitType

EXPECTED_COUNTS = {
    "Flat 1A": 10, "Flat 1B": 18, "Flat 2A": 10, "Flat 2B": 18, "Flat 3A": 3,
    "Flat 3B": 27, "Flat 4A": 2, "Flat 4B": 24, "Flat 5A": 8, "Flat 5B": 18,
    "Flat 6": 28, "Flat 7": 26, "Flat 8": 30, "Flat 9": 28, "Flat 10": 28,
}


def test_thirty_seven_floors(model):
    assert len(model.floors) == 37


def test_total_flats_matches_room_conf_l41(model):
    flats = sum(model.unit_count(u.id) for u in model.unit_types
                if u.is_residential and u.code.startswith("Flat"))
    assert flats == 278


def test_total_offices_matches_room_conf_d41(model):
    offices = sum(model.unit_count(u.id) for u in model.unit_types
                  if u.classification == "Office")
    assert offices == 32


@pytest.mark.parametrize("code,expected", sorted(EXPECTED_COUNTS.items()))
def test_each_type_count(model, code, expected):
    assert model.unit_count(unit_type(model, code).id) == expected


def test_bhk_split_matches_l43_l45(model):
    split = model.counts_by_classification()
    assert split["1BHK"] == 28
    assert split["2BHK"] == 143
    assert split["3BHK"] == 107
    assert split["1BHK"] + split["2BHK"] + split["3BHK"] == 278


def test_c21_adding_a_unit_type_updates_the_split_with_no_code_change(model):
    """The defect: Room Conf!L44 = M40+O40+R40+U40+V40+Y40+Z40+P40 is a
    hand-typed list of columns, with P40 appended out of sequence -- the scar
    of a type added after the formula was written. Add a sixteenth type and
    the workbook's split silently stops adding up."""
    before = model.counts_by_classification()["2BHK"]
    new_type = UnitType(id="test-flat-11", project_id=model.project.id,
                        code="Flat 11", classification="2BHK", seq=99)
    model.unit_types.append(new_type)
    model.floor_unit_mix.append(FloorUnitMix(
        id="test-mix", floor_id=model.floors[10].id,
        unit_type_id=new_type.id, count=5))
    try:
        assert model.counts_by_classification()["2BHK"] == before + 5
    finally:
        model.unit_types.remove(new_type)
        model.floor_unit_mix.pop()
    assert model.counts_by_classification()["2BHK"] == before


def test_building_height_is_reported_as_height_not_as_a_count(model):
    """Room Conf!C40 = SUM(C3:C39) = 121.40 is labelled 'Total Apartments'.
    It is the sum of floor-to-floor heights: the building's height in metres."""
    height = sum(f.floor_to_floor_ht for f in model.floors)
    assert height == pytest.approx(121.40, abs=0.01)
    flats = sum(model.unit_count(u.id) for u in model.unit_types
                if u.is_residential and u.code.startswith("Flat"))
    assert flats == 278 and height != flats
