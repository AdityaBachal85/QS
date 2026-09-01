"""Unit safety -- the mechanism that makes C-35 impossible."""

import pytest

from qs_engine.units import (Quantity, Rate, UnitConverter, UnitMismatchError,
                             UnknownUnitError, amount, parse_unit)

CONV = UnitConverter(sqm_to_sqft=10.764, ft_to_rm=3.28)


def test_sqm_to_sqft_matches_flat_sizes_e5():
    assert Quantity.of(22.05, "Sq M").to("Sq Ft", CONV).value == pytest.approx(237.3462)


@pytest.mark.parametrize("written", ["Sq M", "SQM", "sq.m", " sq m ", "M2"])
def test_unit_spellings_from_the_workbook_all_resolve(written):
    assert parse_unit(written).code == "SQM"


def test_an_unknown_unit_raises_rather_than_defaulting():
    with pytest.raises(UnknownUnitError):
        parse_unit("furlong")


def test_c35_deducting_door_area_from_skirting_raises():
    """The defect itself.

    Internal Finishes Flats!F6 subtracts Doors!H5+H6+H7+H9 -- door areas in
    sq.m -- from E6, a skirting quantity in running metres.
    """
    skirting = Quantity.of(19.39, "RM")
    door_area = Quantity.of(7.875, "Sq M")
    with pytest.raises(UnitMismatchError, match="area.*length|length.*area"):
        skirting.subtract(door_area)


def test_c35_the_correct_deduction_is_door_width():
    skirting = Quantity.of(19.39, "RM")
    widths = Quantity.of(1.20 + 0.90 + 0.90 + 0.75, "RM")
    assert skirting.subtract(widths).value == pytest.approx(15.64)


def test_the_workbook_over_deducts_by_exactly_the_door_height():
    """Every door in the schedule is 2.1 m high, so the error is a clean 2.1x."""
    widths = 1.20 + 0.90 + 0.90 + 0.75
    assert widths * 2.1 == pytest.approx(7.875)


def test_pricing_a_quantity_against_a_mismatched_rate_raises():
    with pytest.raises(UnitMismatchError):
        amount(Quantity.of(100, "RM"), Rate.of(1340.118, "Sq M"))


def test_amount_matches_cost_sheet_tower_i40():
    got = amount(Quantity.of(18809.63, "Sq M"), Rate.of(1342.8975586749984, "Sq M"))
    assert got == pytest.approx(25259406.2065, rel=1e-9)
