"""Module 4 gate -- the eight build-up methods against Rate List - Flats."""

import pytest

from qs_engine.model import BuildupMethod as M
from qs_engine.model import RateRevision
from qs_engine.params import ParameterSet
from qs_engine.rules.rate_buildup import build_rate

PARAMS = ParameterSet.defaults()


def rev(method, basic=None, laying=None, **kw):
    return RateRevision(id="r", rate_item_id="i", method=method,
                        basic_rate=basic, laying_rate=laying, **kw)


@pytest.mark.parametrize("cell,method,basic,laying,expected", [
    ("G6  flooring",      M.AREA_WITH_WASTAGE,    45, 75, 1340.118),
    ("G7  skirting",      M.LINEAR_WITH_WASTAGE,  45, 70, 391.96),
    ("G9  wall plaster",  M.AREA_SIMPLE,          32, None, 344.448),
    ("G12 wall paint",    M.AREA_SIMPLE,          20, None, 215.28),
    ("G15 frame internal", M.FRAME,              180, 135, 655.9272),
    ("G16 frame external", M.FRAME,               60, 100, 399.0424),
])
def test_acceptance_rates(cell, method, basic, laying, expected):
    assert build_rate(rev(method, basic, laying), PARAMS).value == pytest.approx(expected)


def test_master_rate_is_1340_not_1342():
    """The Phase 1 report conflated two different numbers.

    Rate List - Flats!G6 is the master rate, 1,340.118.  1,342.898 is
    Internal Finishes Flats!E1998, a weighted average back-calculated as
    total amount / total quantity across ~150 room blocks.  The gap between
    them is C-6: a blended rate that exists nowhere in the rate list.
    """
    master = build_rate(rev(M.AREA_WITH_WASTAGE, 45, 75), PARAMS).value
    assert master == pytest.approx(1340.118)
    assert master != pytest.approx(1342.8976, abs=1e-3)


def test_wastage_is_per_revision_not_a_global_constant():
    """G64, toilet dado, uses 1.15 where flooring uses 1.1."""
    dado = rev(M.AREA_WITH_WASTAGE, 50, 80, wastage_pct=0.15)
    assert build_rate(dado, PARAMS).value == pytest.approx(1480.05)


def test_plaster_and_paint_carry_no_wastage():
    """Q-6: the 1.1 applies to flooring, skirting and frames but not to
    plaster or paint. AREA_SIMPLE is the method that says so."""
    plaster = build_rate(rev(M.AREA_SIMPLE, 32), PARAMS)
    assert plaster.value == pytest.approx(32 * 10.764)
    assert "no wastage" in plaster.derivation.note


def test_frame_width_is_per_revision():
    """G102 uses a 2.2 m profile where the rest of the sheet uses 0.1."""
    wide = rev(M.FRAME, 250, 100, frame_width_m=2.2)
    expected = 250 * (2.2 * 1.1 * 10.764) + 100 * 3.28
    assert build_rate(wide, PARAMS).value == pytest.approx(expected)


def test_an_unpriced_rate_returns_zero_and_says_so():
    """C-11: a zero that means 'no price' must be distinguishable from a
    zero that means 'costs nothing'."""
    empty = rev(M.AREA_WITH_WASTAGE)
    result = build_rate(empty, PARAMS)
    assert result.value == 0.0
    assert "MISSING_RATE" in result.derivation.note
    assert not empty.is_priced


def test_changing_a_parameter_moves_every_rate_built_on_it():
    tighter = PARAMS.with_value("wastage_pct", 0.12, reason="revised allowance")
    assert build_rate(rev(M.AREA_WITH_WASTAGE, 45, 75), tighter).value == \
        pytest.approx((45 * 1.12 + 75) * 10.764)


def test_derivation_shows_the_working():
    explained = build_rate(rev(M.AREA_WITH_WASTAGE, 45, 75), PARAMS).derivation.explain()
    assert "45" in explained and "10.764" in explained and "wastage_pct" in explained
