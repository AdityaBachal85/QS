"""Cost lines and the project roll-up.

Three flat sheets carrying Rs 9.66 crore, plus the detailed cost sheets, plus
the number at the bottom.
"""

import pytest

from qs_engine.model import LineStatus
from qs_engine.rules.cost_lines import (compute_cost_lines, excluded,
                                        price_line, section_total, total_cost,
                                        unpriced)
from qs_engine.rules.summary import project_summary
from qs_engine.units import (Quantity, Rate, UnitMismatchError, amount,
                             parse_unit)


@pytest.fixture(scope="module")
def priced(model, params):
    return compute_cost_lines(model, params)


def section(model, code):
    return next(s for s in model.cost_sections if s.code == code)


@pytest.mark.parametrize("code,sheet,cell", [
    ("preliminaries", "Preliminary", "F13"),
    ("amenities", "Amenities", "F29"),
    ("external-development", "Infra", "E13"),
])
def test_each_flat_sheet_folds_to_its_own_total(model, priced, wb, code, sheet, cell):
    """Derived line by line, and equal to the paisa."""
    got = section_total(priced, section(model, code).id)
    assert got == pytest.approx(wb.number(sheet, cell), abs=0.01)


def test_a_typed_amount_becomes_a_rate_times_a_quantity(model, priced):
    """`Infra!E12` holds 15,00,000 where every neighbour is =C*D (C-33).

    The money is unchanged; what changes is that the multiplication is on
    screen instead of a number somebody typed into a computed column.
    """
    misc = next(p for p in priced
                if p.description.strip().lower().startswith("miscellaneous"))
    assert misc.unit == "LS"
    assert misc.qty == 1.0
    assert misc.amount == pytest.approx(1_500_000, abs=0.01)
    assert misc.rate == pytest.approx(1_500_000, abs=0.01)


def test_the_landscape_split_is_a_parameter_not_a_side_calculation(model, params, priced):
    """`Infra!C9` is `=K10`, and K10 is 60% of three areas in a sheet corner."""
    hard = next(p for p in priced if p.description.strip().lower().startswith("hard scape"))
    soft = next(p for p in priced if p.description.strip().lower().startswith("soft scape"))

    components = model.qty_components(hard.line.id)
    assert len(components) == 3, "ground floor, 6th podium and terrace"
    assert all(c.factor_param_key == "hardscape_share_pct" for c in components)

    total_area = sum(c.value for c in components)
    assert hard.qty == pytest.approx(total_area * params["hardscape_share_pct"])
    assert soft.qty == pytest.approx(total_area * params["softscape_share_pct"])
    assert hard.qty + soft.qty == pytest.approx(total_area)


def test_the_shares_sum_to_one(params):
    assert params["hardscape_share_pct"] + params["softscape_share_pct"] == \
        pytest.approx(1.0)


def test_a_lump_sum_cannot_be_priced_per_square_metre():
    """The C-35 guarantee, applied to cost lines."""
    with pytest.raises(UnitMismatchError):
        amount(Quantity.of(1, "LS"), Rate.of(950, "SQM"))


def test_months_are_a_dimension_of_their_own(params):
    """Preliminaries bill 36 months at Rs 36,000; the workbook types 36 thrice."""
    assert parse_unit("Month").dimension.value == "duration"
    assert amount(Quantity.of(36, "MONTH"), Rate.of(36000, "MONTH")) == \
        pytest.approx(1_296_000)
    with pytest.raises(UnitMismatchError):
        amount(Quantity.of(36, "MONTH"), Rate.of(100, "SQM"))


def test_a_heading_carries_its_children_and_is_not_counted_twice(model, priced):
    """Amenities groups seven headings over their own lines."""
    headings = [p for p in priced if p.is_heading]
    assert headings, "Amenities is grouped"

    for heading in headings:
        children = model.children_of(heading.line.id)
        if not children:
            continue
        child_total = sum(p.amount for p in priced
                          if p.line.parent_id == heading.line.id)
        assert heading.amount == pytest.approx(child_total, abs=0.01)

    # The section total counts the children, never the heading as well.
    amenities = section(model, "amenities")
    assert section_total(priced, amenities.id) == pytest.approx(
        sum(p.amount for p in priced
            if p.line.section_id == amenities.id and not p.is_heading), abs=0.01)


def test_every_cost_line_is_priced(priced):
    assert not unpriced(priced), \
        [p.description for p in unpriced(priced)][:5]


def test_the_substation_reaches_the_project_total(model, params, priced):
    """C-38, the whole point of a section being a filter.

    `Cost Sheet Tower!I126` is the Substation at Rs 24,00,000, under the
    MEP EXTERNAL heading which runs to row 126. `Summary!D11` sums I118:I125
    and stops one row short, so the workbook computes it, totals it into its
    own I129, and never carries it into the budget.
    """
    substation = [p for p in priced if "substation" in p.description.lower()]
    assert substation, "the Substation line is imported"

    band = next(s for s in model.cost_sections if s.code.startswith("mep-external"))
    assert all(p.line.section_id == band.id for p in substation)

    total = section_total(priced, band.id)
    assert total == pytest.approx(20_514_360 + 2_400_000, abs=1), \
        "the band totals what the workbook's range misses"


def test_infra_is_not_counted_twice(model, priced):
    """`Cost Sheet Tower!I127` is `=Infra!E13`.

    Importing it as a cost line as well as importing the Infra sheet would
    count Rs 4.66 crore in two places.
    """
    doubled = [p for p in priced
               if "external development civil" in p.description.lower()]
    assert not doubled, "I127 mirrors the Infra section and must not be imported"


def test_the_project_total_is_the_workbook_plus_exactly_the_substation(
        model, params, wb):
    """Every section to the paisa, and one deliberate, predicted difference."""
    area = params["construction_area_sqft"]
    summary = project_summary(model, params, area)

    substation = 2_400_000.0
    uplift = 1 + params["escalation_pct"] + params["contingency_pct"]
    expected_delta = substation * uplift * (1 + params["gst_pct"])

    excel_total = (wb.number("Summary", "D20") or 0.0) * 1e7
    assert summary.total - excel_total == pytest.approx(expected_delta, abs=1.0)


def test_an_excluded_line_keeps_its_value_and_its_reason(model, params, priced):
    """C-2: nothing is removed by multiplying it by zero."""
    from dataclasses import replace

    line = next(p.line for p in priced if not p.is_heading and p.line.qty)
    marked = replace(line, status=LineStatus.EXCLUDED,
                     exclusion_reason="client scope, 12 Feb")
    still = price_line(marked, model, params)

    assert still.amount > 0, "the value survives exclusion"
    assert still.line.exclusion_reason
    assert still not in [x for x in excluded([still]) if not x.line.exclusion_reason]
    assert total_cost([still]) == 0.0, "but it reaches no total"
