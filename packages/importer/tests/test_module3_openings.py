"""Module 3 gate -- doors, windows and railings."""

import pytest

from qs_engine.model import OpeningKind, OpeningType
from qs_engine.rules.schedule import opening_schedule, total_openings

EXCEL_DOORS = {"FRD": 540, "D1": 667, "D2": 695, "K FRD": 278}
EXCEL_WINDOWS = {
    "W1": 524.17, "W2": 799.80, "W3": 684.88, "W4": 4144.34, "W4A": 248.02,
    "W7": 537.50, "W8": 58.39, "V": 298.35, "LW": 388.20, "SW": 954.60,
}
EXCEL_RAILINGS = {"BR": 839.64, "UR": 250.00}


def schedule(model, kinds):
    return {l.code.upper(): l for l in opening_schedule(model, kinds)}


@pytest.mark.parametrize("code,expected",
                         [(c, e) for c, e in EXCEL_DOORS.items() if c != "FRD"])
def test_door_type_counts(model, code, expected):
    assert schedule(model, (OpeningKind.DOOR,))[code].count == pytest.approx(expected)


def test_frd_differs_by_exactly_two_because_of_c36(model):
    """C-36: the two smoke-check lobbies are 36 in Flat Sizes!H156/H157 and 37
    in Doors!K137/K138. Both typed, neither a formula. The platform holds one
    count per entity, so the door total is 2 lower than the workbook's."""
    got = schedule(model, (OpeningKind.DOOR,))["FRD"].count
    assert got == pytest.approx(538)
    assert EXCEL_DOORS["FRD"] - got == 2


def test_total_doors_is_2178_and_the_gap_is_explained(model):
    total = total_openings(model, (OpeningKind.DOOR,)).value
    assert total == pytest.approx(2178)
    assert 2180 - total == 2


def test_c12_the_door_count_and_the_money_come_from_the_same_fold(model):
    """Doors!E141, labelled 'Total Doors', is SUBTOTAL(9,E67:E140) = 58 while
    every other total on that row starts at row 5 and reports 2,180. It counts
    the back half of the schedule."""
    total = total_openings(model, (OpeningKind.DOOR,)).value
    assert total > 2000 and total != 58


@pytest.mark.parametrize("code,expected", sorted(EXCEL_WINDOWS.items()))
def test_window_areas(model, code, expected):
    line = schedule(model, (OpeningKind.WINDOW, OpeningKind.VENTILATOR))[code]
    assert line.unit == "SQM"
    assert line.quantity == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("code,expected", sorted(EXCEL_RAILINGS.items()))
def test_railings_are_measured_in_running_metres(model, code, expected):
    """The workbook lists BR and UR under 'Sq M' while their quantities are
    lengths typed into Windows!K, against a D&W Schedule row with no
    dimensions at all."""
    line = schedule(model, (OpeningKind.RAILING,))[code]
    assert line.unit == "RM"
    assert line.quantity == pytest.approx(expected, abs=0.01)


def test_c18_a_fifth_door_type_appears_without_widening_any_range(model):
    """Cost Sheet Tower's VLOOKUPs are bounded to Doors!D146:H149 -- four door
    types. A fifth returns #N/A or is silently dropped."""
    before = len(schedule(model, (OpeningKind.DOOR,)))
    extra = OpeningType(id="test-d3", project_id=model.project.id, code="D3",
                        kind=OpeningKind.DOOR, width_m=0.8, height_m=2.1)
    model.opening_types.append(extra)
    room = model.unit_type_rooms[0]
    from qs_engine.model import RoomOpening
    model.room_openings.append(RoomOpening(
        id="test-ro", unit_type_room_id=room.id, opening_type_id=extra.id, count=1))
    try:
        after = schedule(model, (OpeningKind.DOOR,))
        assert "D3" in after
        assert len(after) == before + 1
    finally:
        model.opening_types.remove(extra)
        model.room_openings.pop()


def test_openings_are_attached_to_rooms(model):
    """The precondition for deductions being a rule rather than a cell list."""
    rooms = {r.id for r in model.unit_type_rooms}
    assert model.room_openings
    assert all(o.unit_type_room_id in rooms for o in model.room_openings)
