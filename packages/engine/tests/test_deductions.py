"""The deduction rules -- and C-35, the defect that motivated them."""

import pytest

from qs_engine.model import (OpeningKind, OpeningType, Project, ProjectModel,
                             RoomCategory, RoomOpening, RoomType, UnitType,
                             UnitTypeRoom)
from qs_engine.params import ParameterSet
from qs_engine.rules.room_qty import (NegativeNetQuantityError,
                                      compute_room_quantity)
from qs_engine.units import UnitMismatchError

PARAMS = ParameterSet.defaults()


@pytest.fixture
def flat_1a_living():
    """Flat 1A's Multi Purpose Room, as the workbook has it.

    Area 22.05, perimeter 19.39, and four doors opening off it: the flat
    entrance (FRD), the kitchen door (K FRD), a bedroom door (D1) and a toilet
    door (D2) -- exactly the set Internal Finishes Flats!F6 picks by hand.
    """
    model = ProjectModel(project=Project(id="p", code="T", name="Test"))
    model.unit_types.append(UnitType(id="ut", project_id="p", code="Flat 1A"))
    model.room_types.append(RoomType(id="rt", project_id="p", name="Multi Purpose Room",
                                     category=RoomCategory.HABITABLE))
    room = UnitTypeRoom(id="room", unit_type_id="ut", room_type_id="rt", seq=1,
                        label="Multi Purpose Room", carpet_area_sqm=22.05,
                        perimeter_m=19.39, clear_height_m=3.1)
    model.unit_type_rooms.append(room)
    for code, width in (("FRD", 1.20), ("K FRD", 0.90), ("D1", 0.90), ("D2", 0.75)):
        model.opening_types.append(OpeningType(
            id=f"op-{code}", project_id="p", code=code, kind=OpeningKind.DOOR,
            width_m=width, height_m=2.10))
        model.room_openings.append(RoomOpening(
            id=f"ro-{code}", unit_type_room_id="room", opening_type_id=f"op-{code}"))
    model.opening_types.append(OpeningType(id="op-W1", project_id="p", code="W1",
                                           kind=OpeningKind.WINDOW,
                                           width_m=5.30, height_m=2.15))
    model.room_openings.append(RoomOpening(id="ro-W1", unit_type_room_id="room",
                                           opening_type_id="op-W1"))
    return model, room


def test_floor_area_matches_e5(flat_1a_living):
    model, room = flat_1a_living
    result = compute_room_quantity(room, "floor_area", model, PARAMS)
    assert result.net.value == pytest.approx(22.05)
    assert result.net.unit.code == "SQM"


def test_wall_gross_matches_e8(flat_1a_living):
    """Internal Finishes Flats!E8 = D4*(D1-0.15) = 19.39 * 2.95."""
    model, room = flat_1a_living
    result = compute_room_quantity(room, "wall_finish", model, PARAMS)
    assert result.gross.value == pytest.approx(57.2005)


def test_wall_deducts_door_and_window_areas(flat_1a_living):
    model, room = flat_1a_living
    result = compute_room_quantity(room, "wall_finish", model, PARAMS)
    doors = (1.20 + 0.90 + 0.90 + 0.75) * 2.10
    window = 5.30 * 2.15
    assert result.deduction.value == pytest.approx(doors + window)
    assert result.deduction.unit.code == "SQM"


def test_c35_skirting_deducts_width_not_area(flat_1a_living):
    """The defect. Internal Finishes Flats!F6 = -7.875 -- the sum of four door
    *areas*, in sq.m -- deducted from a running-metre skirting quantity.

    Correct: 1.20 + 0.90 + 0.90 + 0.75 = 3.75 RM.
    Workbook: 3.75 x 2.1 = 7.875, which is 2.1x too large.
    """
    model, room = flat_1a_living
    result = compute_room_quantity(room, "skirting", model, PARAMS)

    assert result.gross.value == pytest.approx(19.39)
    assert result.gross.unit.code == "RM"
    assert result.deduction.unit.code == "RM"
    assert result.deduction.value == pytest.approx(3.75)
    assert result.net.value == pytest.approx(15.64)

    assert result.deduction.value != pytest.approx(7.875)
    assert result.net.value != pytest.approx(11.515)


def test_c35_the_engine_refuses_the_workbook_arithmetic():
    from qs_engine.units import Quantity
    with pytest.raises(UnitMismatchError):
        Quantity.of(19.39, "RM").subtract(Quantity.of(7.875, "SQM"))


def test_c13_a_door_added_to_a_room_changes_the_deduction_by_itself(flat_1a_living):
    """The workbook's deduction is a hand-picked list of cell addresses --
    -(Doors!H5+Doors!H6+Doors!H7+Doors!H9) -- written ~150 times, with
    Doors!H8 absent and no record of whether that was deliberate."""
    model, room = flat_1a_living
    before = compute_room_quantity(room, "skirting", model, PARAMS).net.value
    model.opening_types.append(OpeningType(id="op-D9", project_id="p", code="D9",
                                           kind=OpeningKind.DOOR,
                                           width_m=0.80, height_m=2.10))
    model.room_openings.append(RoomOpening(id="ro-D9", unit_type_room_id="room",
                                           opening_type_id="op-D9"))
    after = compute_room_quantity(room, "skirting", model, PARAMS).net.value
    assert before - after == pytest.approx(0.80)


def test_windows_do_not_deduct_from_skirting(flat_1a_living):
    """Skirting runs along the floor; a window does not interrupt it."""
    model, room = flat_1a_living
    result = compute_room_quantity(room, "skirting", model, PARAMS)
    assert result.deduction.value == pytest.approx(3.75)


def test_ceiling_takes_no_deduction(flat_1a_living):
    model, room = flat_1a_living
    result = compute_room_quantity(room, "ceiling_area", model, PARAMS)
    assert result.deduction.value == 0.0
    assert result.net.value == pytest.approx(22.05)


def test_over_deduction_raises_instead_of_going_negative(flat_1a_living):
    """Excel adds a negative number -- G = E + F -- so an over-deduction just
    flows through into the cost."""
    model, room = flat_1a_living
    room.perimeter_m = 2.0
    with pytest.raises(NegativeNetQuantityError, match="NEGATIVE_NET_QTY"):
        compute_room_quantity(room, "skirting", model, PARAMS)


def test_slab_allowance_is_a_parameter_not_a_hardcoded_015(flat_1a_living):
    model, room = flat_1a_living
    thicker = PARAMS.with_value("slab_allowance_m", 0.20)
    result = compute_room_quantity(room, "wall_finish", model, thicker)
    assert result.gross.value == pytest.approx(19.39 * (3.1 - 0.20))
