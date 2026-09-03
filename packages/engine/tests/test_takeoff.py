"""The finishing take-off -- quantities meeting rates."""

import pytest

from qs_engine.rules.takeoff import (LineStatus, by_finish, compute_takeoff,
                                     total_amount, unpriced)


@pytest.fixture(scope="module")
def lines(model, params):
    return compute_takeoff(model, params)


def test_every_room_with_a_schedule_produces_lines(lines):
    assert len(lines) > 1000
    assert sum(1 for l in lines if l.is_priced) > 1000


def test_the_finishing_total_is_within_reach_of_the_workbook(lines, wb):
    """Against `Internal Finishes Flats!F2040`, corrected for its own duplicate.

    Row 2010 "Vitrified Skirt" repeats row 1999 "Vitrfied Skirting - Flats"
    exactly -- same quantity, same amount -- and F2040 counts both (C-15).
    """
    printed = wb.number("Internal Finishes Flats", "F2040")
    duplicate = wb.number("Internal Finishes Flats", "F2010")
    corrected = printed - duplicate
    got = total_amount(lines)

    assert corrected == pytest.approx(215_044_617, abs=1)
    assert got == pytest.approx(corrected, rel=0.02), (
        f"platform {got:,.0f} against corrected Excel {corrected:,.0f}")


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
