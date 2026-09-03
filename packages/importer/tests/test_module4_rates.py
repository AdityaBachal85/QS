"""Module 4 gate -- the rate library, and the proof that C-6 is dead."""

import pytest

from qs_engine.model import BuildupMethod, RateItem, RateRevision
from qs_engine.rules.rate_buildup import build_rate, effective_rate
from qs_importer.mappers.rates import classify_formula


def priced_rows(wb, sheet, last_row):
    """Every row of a rate list that carries a formula and a cached value."""
    for row in range(4, last_row + 1):
        value = wb.number(sheet, f"G{row}")
        formula = wb.formula(sheet, f"G{row}")
        if value is None or not formula:
            continue
        yield row, formula, value


@pytest.mark.parametrize("sheet,last_row",
                         [("Rate List - Flats", 300), ("Rate List - Office", 400)])
def test_every_priced_row_reproduces_exactly(wb, params, sheet, last_row):
    """The whole rate list, row by row, against its own cached values."""
    mismatches = []
    checked = 0
    for row, formula, expected in priced_rows(wb, sheet, last_row):
        method, wastage, factor, constant, frame_w = classify_formula(formula, expected)
        if method is BuildupMethod.LINK:
            continue
        revision = RateRevision(
            id=f"{sheet}!G{row}", rate_item_id="x", method=method,
            basic_rate=wb.number(sheet, f"E{row}"),
            laying_rate=wb.number(sheet, f"F{row}"),
            wastage_pct=wastage, adjustment_factor=factor,
            adjustment_constant=constant, frame_width_m=frame_w,
            constant_value=expected if method is BuildupMethod.CONSTANT else None)
        got = build_rate(revision, params).value
        checked += 1
        if abs(got - expected) > 0.01:
            mismatches.append(f"{sheet}!G{row} {formula}: excel {expected} got {got}")
    assert checked > 40
    assert not mismatches, "\n".join(mismatches)


def test_the_eight_methods_cover_the_whole_sheet(model):
    used = {r.method for r in model.rate_revisions}
    assert used <= set(BuildupMethod)
    assert len(used) >= 7


def test_c6_inserting_a_rate_row_changes_nothing(model, params):
    """The defect this whole design exists to remove.

    Internal Finishes Flats!B5 = 'Rate List - Flats'!B6, B6 = !B7, and so on
    across ~150 blocks, each re-anchored by a person counting rows. Insert one
    row in the rate list and flooring picks up the skirting rate. Excel adjusts
    the references it can see, but the offsets *between* blocks were never a
    formula -- so it recalculates cleanly, raises no error, and is wrong by a
    plausible-looking margin.

    Here every reference is by rate_item_id, so position carries no meaning.
    """
    def snapshot():
        out = {}
        for spec in model.room_finish_specs:
            if not spec.rate_item_id:
                continue
            item = model.rate_item(spec.rate_item_id)
            out[spec.id] = (item.description,
                            round(effective_rate(item, model, params).value, 6))
        return out

    before = snapshot()
    assert len(before) > 100

    intruder = RateItem(id="intruder", project_id=model.project.id, code="XXX",
                        description="Inserted row", unit="Sq M")
    revision = RateRevision(id="intruder-rev", rate_item_id="intruder",
                            method=BuildupMethod.AREA_WITH_WASTAGE,
                            basic_rate=999, laying_rate=999)
    model.rate_items.insert(5, intruder)
    model.rate_revisions.insert(5, revision)
    try:
        after = snapshot()
    finally:
        model.rate_items.remove(intruder)
        model.rate_revisions.remove(revision)

    assert after == before, "inserting a rate row moved a downstream rate"


def test_c6_reordering_the_whole_library_changes_nothing(model, params):
    def snapshot():
        return {s.id: round(effective_rate(model.rate_item(s.rate_item_id),
                                           model, params).value, 6)
                for s in model.room_finish_specs if s.rate_item_id}

    before = snapshot()
    model.rate_items.reverse()
    try:
        assert snapshot() == before
    finally:
        model.rate_items.reverse()


def test_acceptance_rates_survive_the_import(model, params):
    """The six named rates, reached through the imported library rather than
    constructed in a test."""
    wanted = {
        ("flooring", "2'x2' vitrified tiles"): 1340.118,
        ("skirting", "2'x2' vitrified tiles"): 391.96,
        ("wall finishes plaster", "gypsum plaster"): 344.448,
        ("wall finishes paint", "plastic paint"): 215.28,
        ("window frames - internal", "granite window frame"): 655.9272,
        ("window frames - external", "marble window frames with sill"): 399.0424,
    }
    seen = {}
    for item in model.rate_items:
        key = (item.description.strip().lower(), item.specification.strip().lower())
        if key in wanted:
            seen.setdefault(key, effective_rate(item, model, params).value)
    for key, expected in wanted.items():
        assert key in seen, f"{key} not found in the imported library"
        assert seen[key] == pytest.approx(expected, abs=0.01)


def test_unpriced_items_are_blocking_not_zero(model, params):
    """C-11: an item with a quantity and no rate is an error, not a zero.

    Built rather than found, because the AVS list happens to contain none once
    the "N.A." rows are recognised for what they are -- and a gate that only
    fires on one workbook is not a gate.
    """
    import copy

    from qs_engine.model import BuildupMethod, RateItem, RateRevision
    from qs_engine.validation import Severity, validate

    m = copy.deepcopy(model)
    m.rate_items.append(RateItem(
        id="forgotten", project_id=m.project.id, code="FORGOT",
        description="Granite Basin Counter", unit="SQM",
        specification="Granite, 18mm"))
    m.rate_revisions.append(RateRevision(
        id="forgotten-rev", rate_item_id="forgotten",
        method=BuildupMethod.AREA_SIMPLE))

    report = validate(m, params, only=["MISSING_RATE"])
    assert report.blocking
    assert not report.can_issue
    assert all(f.severity is Severity.BLOCKING for f in report.blocking)
    assert any(f.entity_id == "forgotten" for f in report.blocking)


def test_a_finish_the_rate_list_calls_N_A_is_not_a_missing_price(model, params):
    """Two different things that looked identical.

    100 rate rows carry a specification of "N.A." -- the rate list saying a
    finish does not apply to that room -- and the take-off tests it 1,790 times
    as ``IF(I5="N.A",0,...)``. Every one was being reported as work somebody
    forgot to price, and the false alarms buried the real ones.
    """
    from qs_engine.validation import validate

    excluded = [i for i in model.rate_items
                if str(i.specification).strip().upper().rstrip(".") in ("N.A", "NA")]
    assert excluded, "the AVS rate lists mark finishes N.A."

    report = validate(model, params, only=["MISSING_RATE"])
    flagged = {f.entity_id for f in report.blocking}
    assert not flagged & {i.id for i in excluded}, \
        "an explicitly excluded finish is not an unpriced one"


def test_a_room_type_carrying_a_slot_twice_is_reported(model, params):
    """`Lift Lobby` heads a block in both rate lists, with different specs.

    Both fold into one room type, so every room priced on it picks the slot up
    twice. Reported rather than merged or split: splitting moves the finishing
    take-off 16% away from the workbook, and a difference nobody can explain
    must not be applied quietly.
    """
    from qs_engine.validation import validate

    report = validate(model, params, only=["DUPLICATE_FINISH_SCHEDULE"])
    names = {f.entity_id for f in report.findings}
    assert names, "the AVS rate lists repeat three block names"
    assert any("lift-lobby" in n for n in names)
