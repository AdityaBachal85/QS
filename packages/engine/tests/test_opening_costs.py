"""Doors and windows, priced.

The schedule always folded counts and areas correctly. What it did not do was
carry money: `D&W Schedule` column F holds a rate against every type and
nothing read it, so 2,178 doors and 9,728 sq.m of glazing had quantities and
no cost.
"""

import pytest

from qs_engine.model import OpeningKind
from qs_engine.rules.schedule import (NO_QUANTITY, opening_totals,
                                      priced_opening_schedule,
                                      total_opening_amount)
from qs_engine.units import Quantity, Rate, UnitMismatchError, amount


@pytest.fixture(scope="module")
def priced(model, params):
    return priced_opening_schedule(model, params)


def test_every_opening_type_carries_a_rate(model):
    """All 26, from `D&W Schedule` column F."""
    missing = [o.code for o in model.opening_types if not o.rate_item_id]
    assert not missing, f"opening types with no rate: {missing}"


def test_a_door_is_priced_by_the_leaf_and_glazing_by_the_square_metre(priced):
    door = next(l for l in priced if l.code == "FRD")
    window = next(l for l in priced if l.code == "W4")

    assert door.rate_unit == "NOS"
    assert door.amount == pytest.approx(door.count * door.rate)

    assert window.rate_unit == "SQM"
    assert window.amount == pytest.approx(window.quantity * window.rate)


def test_a_per_leaf_rate_against_an_area_refuses_to_multiply(params):
    """The C-35 guarantee, applied to openings."""
    with pytest.raises(UnitMismatchError):
        amount(Quantity.of(1355.76, "SQM"), Rate.of(30000, "NOS"))


def test_the_glazing_total_matches_the_workbook_to_the_paisa(model, params, wb):
    """`Windows!H178` sums windows, the ventilator and both railings."""
    bands = {t.key: t for t in opening_totals(model, params)}
    got = sum(bands[k].amount for k in ("windows", "ventilators", "railings"))
    assert got == pytest.approx(wb.number("Windows", "H178"), abs=0.01)


def test_the_door_total_is_the_workbook_less_the_two_smoke_check_doors(
        model, params, wb):
    """C-36: 36 lobbies in Flat Sizes, 37 in Doors. Two FRD at Rs 30,000."""
    bands = {t.key: t for t in opening_totals(model, params)}
    assert bands["doors"].amount == pytest.approx(
        wb.number("Doors", "H150") - 60_000, abs=0.01)


def test_the_rate_keeps_its_conversion_factor_as_a_parameter(model, params):
    """`=550*10.764` imports as 550 per sq.ft, not as a constant Rs 5,920.20.

    Baking the product in would make the window rates immovable when the
    project's sq.m/sq.ft factor changes.
    """
    from qs_engine.model import BuildupMethod

    window = next(o for o in model.opening_types if o.code == "W4")
    revision = model.current_revision(window.rate_item_id)
    assert revision.method is BuildupMethod.AREA_SIMPLE
    assert revision.basic_rate == pytest.approx(550.0)


def test_a_priced_type_that_reaches_no_room_is_reported_not_dropped(priced):
    """The eight curtain-wall bays: Rs 3.30 crore priced and never measured."""
    bays = [l for l in priced if l.kind is OpeningKind.CURTAIN_WALL]
    assert len(bays) == 8
    for bay in bays:
        assert bay.status == NO_QUANTITY
        assert bay.rate > 0
        assert bay.amount == 0
        assert "reaches no total" in bay.message


def test_the_bands_add_up_to_the_total(model, params):
    bands = opening_totals(model, params)
    assert sum(b.amount for b in bands) == pytest.approx(
        total_opening_amount(model, params), abs=0.01)
