"""The genericity gate.

A second project, built from nothing, with a shape AVS does not have: a
different floor count, a unit type with four bathrooms and no balcony, and a
room type this codebase has never seen.  It must compute end to end with no
code change.  If this test ever needs one, the model is wrong.
"""

import pytest

from qs_engine.model import (Building, BuildupMethod, Floor, FloorType,
                             FloorUnitMix, OpeningKind, OpeningType, Project,
                             ProjectModel, RateItem, RateRevision, RoomCategory,
                             RoomOpening, RoomType, UnitType, UnitTypeRoom)
from qs_engine.params import ParameterSet
from qs_engine.rules.rate_buildup import effective_rate
from qs_engine.rules.room_qty import compute_room_quantity
from qs_engine.rules.schedule import opening_schedule
from qs_engine.rules.unit_area import unit_type_area_sqft, unit_type_total_sqft
from qs_engine.units import Quantity, Rate, UnitConverter, amount

PARAMS = ParameterSet.defaults()
CONV = UnitConverter(PARAMS["factor_sqm_to_sqft"], PARAMS["factor_ft_to_rm"])


@pytest.fixture
def villa_project():
    """Twelve floors, one unit type: four bathrooms, no balcony, a home
    theatre and a puja room -- neither of which exists in AVS."""
    model = ProjectModel(project=Project(id="v", code="VLA", name="Villa Project"))
    model.buildings.append(Building(id="b", project_id="v", name="Block A"))
    for seq in range(1, 13):
        model.floors.append(Floor(id=f"f{seq}", building_id="b", seq=seq,
                                  name=f"Floor {seq}", floor_to_floor_ht=3.3,
                                  floor_type=FloorType.TYPICAL))
    model.unit_types.append(UnitType(id="ut", project_id="v", code="Villa A",
                                     classification="4BHK"))
    for seq, floor in enumerate(model.floors, start=1):
        model.floor_unit_mix.append(FloorUnitMix(
            id=f"m{seq}", floor_id=floor.id, unit_type_id="ut", count=2))

    rooms = [
        ("Living", RoomCategory.HABITABLE, 38.0, 26.0),
        ("Home Theatre", RoomCategory.HABITABLE, 22.0, 19.0),
        ("Puja Room", RoomCategory.HABITABLE, 4.5, 8.6),
        ("M. Toilet", RoomCategory.TOILET, 4.2, 8.4),
        ("C. Toilet", RoomCategory.TOILET, 3.6, 7.8),
        ("Guest Toilet", RoomCategory.TOILET, 3.1, 7.2),
        ("Powder Room", RoomCategory.TOILET, 2.4, 6.4),
    ]
    for seq, (name, category, area, perimeter) in enumerate(rooms, start=1):
        model.room_types.append(RoomType(id=f"rt{seq}", project_id="v",
                                         name=name, category=category))
        model.unit_type_rooms.append(UnitTypeRoom(
            id=f"r{seq}", unit_type_id="ut", room_type_id=f"rt{seq}", seq=seq,
            label=name, carpet_area_sqm=area, perimeter_m=perimeter,
            clear_height_m=3.15))

    model.opening_types.append(OpeningType(id="op-d", project_id="v", code="D1",
                                           kind=OpeningKind.DOOR,
                                           width_m=0.90, height_m=2.10))
    for seq in range(1, len(rooms) + 1):
        model.room_openings.append(RoomOpening(
            id=f"ro{seq}", unit_type_room_id=f"r{seq}", opening_type_id="op-d"))

    model.rate_items.append(RateItem(id="ri", project_id="v", code="FLR",
                                     description="Flooring", unit="Sq M"))
    model.rate_revisions.append(RateRevision(
        id="rev", rate_item_id="ri", method=BuildupMethod.AREA_WITH_WASTAGE,
        basic_rate=60, laying_rate=80))
    return model


def test_four_bathrooms_and_no_balcony_is_just_rows(villa_project):
    rooms = villa_project.rooms_of("ut")
    toilets = [r for r in rooms
               if villa_project.room_type(r.room_type_id).category is RoomCategory.TOILET]
    balconies = [r for r in rooms
                 if villa_project.room_type(r.room_type_id).category is RoomCategory.BALCONY]
    assert len(toilets) == 4
    assert balconies == []
    assert len(rooms) == 7


def test_room_types_absent_from_avs_need_no_code_change(villa_project):
    names = {rt.name for rt in villa_project.room_types}
    assert {"Home Theatre", "Puja Room", "Powder Room"} <= names


def test_unit_counts_derive_from_a_different_floor_count(villa_project):
    assert len(villa_project.floors) == 12
    assert villa_project.unit_count("ut") == 24
    assert villa_project.counts_by_classification() == {"4BHK": 24}


def test_areas_compute(villa_project):
    per_unit = unit_type_area_sqft("ut", villa_project, PARAMS).value
    expected = sum(r.carpet_area_sqm for r in villa_project.rooms_of("ut")) * 10.764
    assert per_unit == pytest.approx(expected)
    assert unit_type_total_sqft("ut", villa_project, PARAMS).value == \
        pytest.approx(per_unit * 24)


def test_deductions_compute_for_every_room(villa_project):
    for room in villa_project.rooms_of("ut"):
        skirting = compute_room_quantity(room, "skirting", villa_project, PARAMS)
        assert skirting.deduction.unit.code == "RM"
        assert skirting.deduction.value == pytest.approx(0.90)
        assert skirting.net.value == pytest.approx(room.perimeter_m - 0.90)


def test_the_schedule_computes(villa_project):
    lines = opening_schedule(villa_project, (OpeningKind.DOOR,))
    assert len(lines) == 1
    assert lines[0].count == pytest.approx(7 * 24)


def test_rates_and_amounts_compute(villa_project):
    item = villa_project.rate_item("ri")
    rate = effective_rate(item, villa_project, PARAMS).value
    assert rate == pytest.approx((60 * 1.1 + 80) * 10.764)
    room = villa_project.rooms_of("ut")[0]
    qty = compute_room_quantity(room, "floor_area", villa_project, PARAMS).net
    assert amount(qty, Rate.of(rate, "Sq M"), CONV) == pytest.approx(38.0 * rate)


def test_a_second_project_shares_nothing_with_the_first(villa_project, model):
    """No global state, no shared registry keyed by project shape."""
    assert villa_project.project.id != model.project.id
    assert villa_project.unit_count("ut") == 24
    assert len(model.floors) == 37 and len(villa_project.floors) == 12
