"""The finishing take-off -- quantities meeting rates."""

import pytest

from qs_engine.rules.takeoff import (LineStatus, by_finish, compute_takeoff,
                                     total_amount, unpriced)


@pytest.fixture(scope="module")
def lines(model, params):
    return compute_takeoff(model, params)


@pytest.fixture(scope="module")
def flat_height_lines(model, params):
    """The same take-off measured the way the workbook measures it.

    Every wall at the project default rather than at its own floor's height, so
    the two can be differenced and the floor-height effect stated as a figure
    instead of assumed.
    """
    saved = model.height_placements
    model.height_placements = lambda unit_type_id: []
    try:
        return compute_takeoff(model, params)
    finally:
        model.height_placements = saved


def height_effect(lines, flat_lines):
    return total_amount(lines) - total_amount(flat_lines)


def test_every_room_with_a_schedule_produces_lines(lines):
    assert len(lines) > 1000
    assert sum(1 for l in lines if l.is_priced) > 1000


def test_the_finishing_total_is_within_reach_of_the_workbook(
        lines, flat_height_lines, wb):
    """Against `Internal Finishes Flats!F2040`, corrected for its own duplicate.

    Row 2010 "Vitrified Skirt" repeats row 1999 "Vitrfied Skirting - Flats"
    exactly -- same quantity, same amount -- and F2040 counts both (C-15).
    """
    printed = wb.number("Internal Finishes Flats", "F2040")
    duplicate = wb.number("Internal Finishes Flats", "F2010")
    corrected = printed - duplicate
    got = total_amount(lines)

    assert corrected == pytest.approx(215_044_617, abs=1)

    # The workbook measures every wall at 3.1 m (`Internal Finishes Flats!D1`,
    # hard-coded per block); we measure each at its own floor's height.  That
    # difference is deliberate, so it is subtracted out by name rather than
    # widening the tolerance until it fits.  What is left is the genuinely
    # unexplained residual, and it is what this gate holds.
    residual = got - height_effect(lines, flat_height_lines)
    assert residual == pytest.approx(corrected, rel=0.02), (
        f"platform {got:,.0f} less the floor-height effect gives "
        f"{residual:,.0f}, against corrected Excel {corrected:,.0f}")


def test_a_line_carries_its_quantity_its_rate_and_its_amount(lines):
    line = next(l for l in lines if l.is_priced and l.finish_name == "Flooring")
    assert line.net > 0 and line.rate > 0
    assert line.total_qty == pytest.approx(line.net * line.unit_count, rel=1e-9)
    assert line.total_amount == pytest.approx(line.total_qty * line.rate, rel=1e-6)


def test_skirting_deducts_width_so_its_unit_is_running_metres(lines):
    """C-35, end to end: a linear quantity takes a linear deduction."""
    line = next(l for l in lines if l.finish_name == "Skirting" and l.deduction)
    assert line.unit == "RM"
    assert line.deduction < line.gross


def test_measured_work_with_no_rate_is_reported_not_zeroed(lines):
    """C-11: `Cost Sheet Tower!I99` shows Rs 0 against 4,508 sq.m of false
    ceiling while the cell beside it works out Rs 65.5 lakh."""
    missing = unpriced(lines)
    assert missing, "the workbook has measured, unpriced work and so should we"
    for line in missing:
        assert line.total_qty > 0
        assert line.total_amount == 0
        assert line.status == LineStatus.NO_RATE
        assert "no price" in line.message or "no rate" in line.message


def test_unpriced_lines_are_excluded_from_the_total(lines):
    assert total_amount(lines) == sum(l.total_amount for l in lines if l.is_priced)


def test_grouping_is_a_filter_not_a_range(lines):
    """Add a finish tomorrow and it is counted because it matches."""
    groups = by_finish(lines)
    assert sum(g.amount for g in groups) == pytest.approx(total_amount(lines), rel=1e-9)


def test_blended_rate_is_shown_as_what_it_is(lines):
    """The workbook prices its cost sheet on amount / quantity -- a weighted
    average existing in no rate list (C-6). It is reported, not relied on."""
    flooring = next(g for g in by_finish(lines) if g.label == "Flooring")
    assert flooring.blended_rate == pytest.approx(
        flooring.amount / flooring.quantity)
    assert flooring.blended_rate != pytest.approx(1340.118, abs=1)


def test_every_priced_line_has_provenance(lines):
    for line in lines[:200]:
        if line.is_priced:
            assert line.gross_derivation is not None
            assert line.rate_derivation is not None


# --------------------------------------------------------------------------
# Floor height -- wall = perimeter x (floor-to-floor height - slab)
# --------------------------------------------------------------------------

def test_wall_height_comes_from_the_floor_not_from_a_default(model, params):
    """The height is the floor's, from Room Config, less the slab allowance.

    The workbook hard-codes 3.1 m for every block, so a Ground Floor wall (4.2 m)
    is measured 1.1 m short on every metre of perimeter.
    """
    from qs_engine.rules.room_qty import compute_room_quantity

    room = next(r for r in model.unit_type_rooms if r.perimeter_m > 0)
    slab = params["slab_allowance_m"]

    ground = compute_room_quantity(room, "wall_finish", model, params,
                                   floor_height_m=4.2)
    typical = compute_room_quantity(room, "wall_finish", model, params,
                                    floor_height_m=3.1)

    assert ground.gross.value == pytest.approx(room.perimeter_m * (4.2 - slab))
    assert typical.gross.value == pytest.approx(room.perimeter_m * (3.1 - slab))
    assert ground.gross.value > typical.gross.value


def test_a_room_with_its_own_height_overrides_the_floor(model, params):
    """A double-height space is not its floor's height."""
    from dataclasses import replace

    from qs_engine.rules.room_qty import compute_room_quantity

    base = next(r for r in model.unit_type_rooms if r.perimeter_m > 0)
    gym = replace(base, clear_height_m=7.0)
    slab = params["slab_allowance_m"]

    q = compute_room_quantity(gym, "wall_finish", model, params, floor_height_m=3.1)
    assert q.gross.value == pytest.approx(base.perimeter_m * (7.0 - slab))


def test_only_height_driven_finishes_split_across_floors(lines, flat_height_lines):
    """Flooring is the same however many heights a unit type spans.

    Splitting a unit type by height must not disturb quantities that do not
    depend on it -- otherwise the fold is silently double-counting.
    """
    def by_rule(rows):
        out = {}
        for line in rows:
            if line.is_priced:
                out[line.qty_rule] = out.get(line.qty_rule, 0.0) + line.total_amount
        return out

    after, before = by_rule(lines), by_rule(flat_height_lines)
    moved = {rule for rule in set(after) | set(before)
             if abs(after.get(rule, 0.0) - before.get(rule, 0.0)) > 0.01}
    assert moved == {"wall_finish"}, f"unexpected movement in {moved - {'wall_finish'}}"


def test_splitting_by_height_preserves_the_unit_count(model, lines):
    """However a unit type is split, the building still has as many of them."""
    for unit in model.unit_types:
        placements = model.height_placements(unit.id)
        if not placements:
            continue
        assert sum(p.count for p in placements) == model.unit_count(unit.id)


def test_a_unit_type_spanning_two_heights_yields_two_wall_lines(model, lines):
    """Offices sit on the podiums at 2.9 m and the ground floor at 4.2 m."""
    spanning = [u for u in model.unit_types
                if len({p.height_m for p in model.height_placements(u.id)}) > 1]
    assert spanning, "the AVS building has unit types on floors of differing heights"

    unit = spanning[0]
    walls = [l for l in lines
             if l.unit_type_id == unit.id and l.qty_rule == "wall_finish"]
    floors = [l for l in lines
              if l.unit_type_id == unit.id and l.qty_rule == "floor_area"]
    assert len({l.floor_height_m for l in walls}) > 1
    assert len({l.floor_height_m for l in floors}) == 1


# --------------------------------------------------------------------------
# Totals -- the whole building, not one block at a time
# --------------------------------------------------------------------------

def test_total_flooring_is_the_sum_of_every_room_that_has_it(lines, params):
    """The figure the workbook never had: one building, one flooring total."""
    from qs_engine.rules.takeoff import by_finish

    flooring = next(g for g in by_finish(lines, params) if g.label == "Flooring")
    expected = sum(l.total_qty for l in lines if l.finish_name == "Flooring")
    assert flooring.quantity == pytest.approx(expected)
    assert flooring.unit == "SQM"


def test_an_area_total_also_reads_in_square_feet(lines, params):
    """A QS reads areas in square feet; the money still comes from square metres."""
    from qs_engine.rules.takeoff import by_finish

    flooring = next(g for g in by_finish(lines, params) if g.label == "Flooring")
    factor = params["factor_sqm_to_sqft"]
    assert flooring.quantity_sqft == pytest.approx(flooring.quantity * factor)
    assert flooring.rate_per_sqft == pytest.approx(
        flooring.amount / flooring.quantity_sqft)


def test_a_linear_total_reports_no_square_feet(lines, params):
    """Skirting is running metres. Converting it to an area would be nonsense."""
    from qs_engine.rules.takeoff import by_finish

    skirting = next(g for g in by_finish(lines, params) if g.label == "Skirting")
    assert skirting.unit == "RM"
    assert skirting.quantity_sqft is None
    assert skirting.rate_per_sqft is None


def test_a_line_that_failed_to_measure_does_not_blank_the_group_unit(lines, params):
    """An unpriced line carries no unit; it must not hide everyone else's.

    Dado has two lines that cannot be measured. Before this was handled, the
    whole Dado total showed no unit and no square feet.
    """
    from qs_engine.rules.takeoff import by_finish

    dado = next(g for g in by_finish(lines, params) if g.label == "Dado")
    assert dado.unpriced > 0
    assert dado.unit == "SQM"
    assert dado.quantity_sqft is not None


def test_totals_by_room_type_cover_the_same_money_as_totals_by_finish(lines, params):
    """Two folds over one set of lines cannot disagree."""
    from qs_engine.rules.takeoff import by_finish, by_room_type

    by_r = sum(g.amount for g in by_room_type(lines, params))
    by_f = sum(g.amount for g in by_finish(lines, params))
    assert by_r == pytest.approx(by_f, abs=0.01)


def test_flooring_in_toilets_is_one_cell_of_the_matrix(lines, params):
    """`by_finish_and_room_type` answers "total flooring area in toilets"."""
    from qs_engine.rules.takeoff import by_finish_and_room_type

    cells = by_finish_and_room_type(lines, params)
    flooring = [c for c in cells if c.label.startswith("Flooring")]
    assert len(flooring) > 5

    cell = flooring[0]
    expected = sum(l.total_qty for l in lines
                   if l.finish_name == "Flooring"
                   and l.room_type_name == cell.label.split(" — ", 1)[1])
    assert cell.quantity == pytest.approx(expected)
