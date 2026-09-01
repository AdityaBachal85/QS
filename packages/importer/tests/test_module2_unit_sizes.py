"""Module 2 gate -- unit sizes, and variable room composition."""

import dataclasses

import pytest

from conftest import unit_type
from qs_engine.rules.unit_area import (room_area_sqft, unit_type_area_sqft,
                                       unit_type_total_sqft)

EXCEL_TYPE_TOTALS = {
    "Flat 1A": 5032.17, "Flat 1B": 13632.39072, "Flat 2A": 4708.1736,
    "Flat 2B": 13589.76528, "Flat 3A": 2269.48176, "Flat 4A": 1512.98784,
    "Flat 4B": 24727.92192, "Flat 5A": 3999.9024, "Flat 5B": 13645.95336,
    "Flat 6": 21230.05248, "Flat 7": 26866.944, "Flat 8": 30703.2336,
    "Flat 9": 21136.62096, "Flat 10": 21208.95504,
}


def test_room_area_matches_flat_sizes_e5(model, params):
    room = model.rooms_of(unit_type(model, "Flat 1A").id)[0]
    assert room.carpet_area_sqm == pytest.approx(22.05)
    assert room_area_sqft(room, params).value == pytest.approx(237.3462)


def test_flat_1b_subtotal_matches_f20(model, params):
    got = unit_type_area_sqft(unit_type(model, "Flat 1B").id, model, params)
    assert got.value == pytest.approx(757.35504, abs=1e-4)


def test_flat_1b_type_total_matches_i11(model, params):
    got = unit_type_total_sqft(unit_type(model, "Flat 1B").id, model, params)
    assert got.value == pytest.approx(13632.39072, abs=1e-3)


@pytest.mark.parametrize("code,expected", sorted(EXCEL_TYPE_TOTALS.items()))
def test_every_flat_type_total(model, params, code, expected):
    got = unit_type_total_sqft(unit_type(model, code).id, model, params)
    assert got.value == pytest.approx(expected, abs=0.01)


def test_c3_flat_3b_balcony_is_derived_not_the_pasted_perimeter(model, params):
    """Flat Sizes!E57 holds the hardcoded number 7.01 where the column formula
    D57*10.764 gives 30.14. 7.01 is G57 -- the perimeter of the same row,
    pasted one column left. It survived because it looked plausible."""
    rooms = model.rooms_of(unit_type(model, "Flat 3B").id)
    balcony = next(r for r in rooms if r.carpet_area_sqm == pytest.approx(2.80))
    assert room_area_sqft(balcony, params).value == pytest.approx(30.1392, abs=1e-3)

    got = unit_type_total_sqft(unit_type(model, "Flat 3B").id, model, params).value
    assert got - 27188.6112 == pytest.approx(23.1292 * 27, abs=0.01)


def test_area_in_sqft_is_not_a_storable_field(model):
    """The structural fix behind C-3: there is nowhere to paste."""
    room = model.unit_type_rooms[0]
    assert not hasattr(room, "area_sqft")
    assert "area_sqft" not in {f.name for f in dataclasses.fields(room)}


def test_room_counts_vary_freely_between_unit_types(model):
    """Five rooms to ten across AVS's fifteen flat types, and nothing counts
    them. A flat with four bathrooms is four rows."""
    sizes = {u.code: len(model.rooms_of(u.id)) for u in model.unit_types
             if u.code.startswith("Flat")}
    assert min(sizes.values()) == 5
    assert max(sizes.values()) == 10


def test_toilet_counts_vary_between_unit_types(model):
    def toilets(code):
        return sum(1 for r in model.rooms_of(unit_type(model, code).id)
                   if model.room_type(r.room_type_id).category.value == "toilet")
    assert toilets("Flat 1A") == 2
    assert toilets("Flat 3B") == 3
