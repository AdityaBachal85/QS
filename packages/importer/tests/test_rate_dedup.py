"""Merging duplicate rates must not move a single rupee."""

import pytest

from qs_engine.rules.rate_buildup import effective_rate


def test_true_duplicates_are_merged(model):
    """Identical description, specification, unit and every priced field."""
    seen = {}
    for item in model.rate_items:
        revision = model.current_revision(item.id)
        if revision is None:
            continue
        key = (item.description.strip().lower(),
               item.specification.strip().lower(),
               revision.basic_rate, revision.laying_rate,
               revision.wastage_pct, revision.method if revision.is_priced else None)
        assert key not in seen, (
            f"{item.description!r} survived the merge twice with an identical "
            f"price -- {seen.get(key)} and {item.id}")
        seen[key] = item.id


def test_the_merge_is_reported_not_silent(avs):
    assert any(w.startswith("Merged") for w in avs.warnings)


def test_same_name_different_price_is_kept_separate(model, params):
    """C-7 territory: the same work at two prices needs a QS, not an importer."""
    by_name: dict[str, set[float]] = {}
    for item in model.rate_items:
        try:
            rate = round(effective_rate(item, model, params).value, 2)
        except Exception:
            continue
        by_name.setdefault(item.description.strip().lower(), set()).add(rate)

    multi = {k: v for k, v in by_name.items() if len(v) > 1}
    assert multi, "the library really does price some items several ways"
    assert len(multi["flooring"]) > 1


@pytest.mark.parametrize("description,basic,expected", [
    ("Flooring", 45, 1340.118),
    ("Skirting", 45, 391.96),
    ("Wall finishes plaster", 32, 344.448),
    ("Wall finishes Paint", 20, 215.28),
    ("Window Frames - Internal", 180, 655.9272),
    ("Dado", 50, 1480.05),
])
def test_no_rate_moved(model, params, description, basic, expected):
    item = next(i for i in model.rate_items
                if i.description == description
                and model.current_revision(i.id).basic_rate == basic)
    assert effective_rate(item, model, params).value == pytest.approx(expected, abs=0.01)


def test_unpriced_items_collapse_to_one_each(model):
    """The screenshot showed 'Skirting' and 'False ceiling' twice each, unpriced.

    An unpriced row computes to zero whatever method was inferred from its empty
    formula, so two of them are one.
    """
    unpriced = [i for i in model.rate_items
                if (r := model.current_revision(i.id)) and not r.is_priced]
    names = [i.description.strip().lower() for i in unpriced]
    assert len(names) == len(set(names)), f"duplicated unpriced rates: {names}"
