"""Building an overall rate from its components.

``Rate List - Flats`` quotes rates per sq.ft or per R.ft and converts them to
per sq.m or per RM inside the formula, mixing four constants into the text:

    G6  = +(E6*1.1+F6)*10.764                      flooring
    G7  = (E7*1.1+F7)*3.28                         skirting
    G9  = +E9*10.764                               plaster -- note: no 1.1
    G15 = (E15*(0.1*1*1.1*10.764))+(F15*3.28)      frames

Sweeping every distinct formula shape across rows 4-300 gives eight methods.
This module is that taxonomy, with the constants replaced by named parameters.

The wastage answer to Q-6 falls straight out of it: the methods that carry the
1.1 are flooring, skirting and frames; plaster and paint use AREA_SIMPLE and do
not.  What was a pattern buried in formula text becomes a visible field.
"""

from __future__ import annotations

from ..model import BuildupMethod, ProjectModel, RateItem, RateRevision
from ..params import ParameterSet
from ..provenance import Derived, Input, derive


class RateBuildupError(Exception):
    """Raised when a revision does not carry the components its method needs."""


def _wastage(revision: RateRevision, params: ParameterSet) -> float:
    """Per-revision wastage, falling back to the project parameter."""
    return revision.wastage_pct if revision.wastage_pct is not None else params["wastage_pct"]


def _adjust_text(revision: RateRevision) -> str:
    parts = ""
    if revision.adjustment_factor != 1.0:
        parts += f" x {revision.adjustment_factor:g}"
    if revision.adjustment_constant:
        parts += f" {revision.adjustment_constant:+g}"
    return parts


def _adjust_inputs(revision: RateRevision) -> list[Input]:
    out: list[Input] = []
    if revision.adjustment_factor != 1.0:
        out.append(Input("adjustment_factor", revision.adjustment_factor,
                         "unexplained factor carried from the workbook formula"))
    if revision.adjustment_constant:
        out.append(Input("adjustment_constant", revision.adjustment_constant,
                         "unexplained rebate carried from the workbook formula"))
    return out


def _require(value: float | None, field: str, revision: RateRevision) -> float:
    """A missing component reads as zero, not as an exception.

    Refusing to compute would hide the item; computing zero and letting
    ``MISSING_RATE`` report it keeps it visible with its quantity attached,
    which is the behaviour C-11 needed and did not get.
    """
    return 0.0 if value is None else float(value)


def build_rate(revision: RateRevision, params: ParameterSet,
               model: ProjectModel | None = None,
               *, _seen: frozenset[str] = frozenset()) -> Derived:
    """Compute one overall rate, with the working shown.

    Returns a :class:`Derived` so the derivation panel can display exactly how
    the number was reached -- which is the whole point of the exercise, since
    the workbook's equivalent is a formula nobody reads.
    """
    if not revision.is_priced and revision.method is not BuildupMethod.LINK:
        return derive(0.0, "unpriced", "no rate components entered", [],
                      note="MISSING_RATE: this item has no price. It is not a "
                           "zero-cost item; it is an unpriced one.")
    method = revision.method
    sqft = params["factor_sqm_to_sqft"]
    rft = params["factor_ft_to_rm"]

    if method is BuildupMethod.AREA_WITH_WASTAGE:
        basic = _require(revision.basic_rate, "basic_rate", revision)
        laying = revision.laying_rate or 0.0
        w = _wastage(revision, params)
        value = (basic * (1 + w) + laying) * sqft
        return derive(
            value, method.value,
            f"({basic:g} x (1 + {w:g}) + {laying:g}) x {sqft:g}",
            [Input("basic_rate", basic), Input("laying_rate", laying),
             Input("wastage_pct", w, "parameter"),
             Input("factor_sqm_to_sqft", sqft, "parameter")],
        )

    if method is BuildupMethod.AREA_SIMPLE:
        basic = _require(revision.basic_rate, "basic_rate", revision)
        value = basic * sqft
        return derive(
            value, method.value, f"{basic:g} x {sqft:g}",
            [Input("basic_rate", basic), Input("factor_sqm_to_sqft", sqft, "parameter")],
            note="no wastage allowance -- plaster and paint (Q-6)",
        )

    if method is BuildupMethod.LINEAR_WITH_WASTAGE:
        basic = _require(revision.basic_rate, "basic_rate", revision)
        laying = revision.laying_rate or 0.0
        w = _wastage(revision, params)
        value = (basic * (1 + w) + laying) * rft
        return derive(
            value, method.value,
            f"({basic:g} x (1 + {w:g}) + {laying:g}) x {rft:g}",
            [Input("basic_rate", basic), Input("laying_rate", laying),
             Input("wastage_pct", w, "parameter"),
             Input("factor_ft_to_rm", rft, "parameter")],
        )

    if method is BuildupMethod.FRAME:
        basic = _require(revision.basic_rate, "basic_rate", revision)
        laying = revision.laying_rate or 0.0
        w = _wastage(revision, params)
        width = (revision.frame_width_m if revision.frame_width_m is not None
                 else params["frame_width_m"])
        value = basic * (width * (1 + w) * sqft) + laying * rft
        return derive(
            value, method.value,
            f"{basic:g} x ({width:g} x (1 + {w:g}) x {sqft:g}) + {laying:g} x {rft:g}",
            [Input("basic_rate", basic), Input("laying_rate", laying),
             Input("frame_width_m", width, "parameter"),
             Input("wastage_pct", w, "parameter"),
             Input("factor_sqm_to_sqft", sqft, "parameter"),
             Input("factor_ft_to_rm", rft, "parameter")],
        )

    if method is BuildupMethod.AREA_SUM:
        basic = _require(revision.basic_rate, "basic_rate", revision)
        laying = revision.laying_rate or 0.0
        value = ((basic + laying) * sqft) * revision.adjustment_factor \
            + revision.adjustment_constant
        return derive(
            value, method.value,
            f"({basic:g} + {laying:g}) x {sqft:g}" + _adjust_text(revision),
            [Input("basic_rate", basic), Input("laying_rate", laying),
             Input("factor_sqm_to_sqft", sqft, "parameter"),
             *_adjust_inputs(revision)],
        )

    if method is BuildupMethod.PASSTHROUGH:
        basic = revision.basic_rate or 0.0
        laying = revision.laying_rate or 0.0
        value = (basic + laying) * revision.adjustment_factor + revision.adjustment_constant
        return derive(
            value, method.value, f"{basic:g} + {laying:g}" + _adjust_text(revision),
            [Input("basic_rate", basic), Input("laying_rate", laying),
             *_adjust_inputs(revision)],
            note="already quoted in the target unit; no conversion",
        )

    if method is BuildupMethod.CONSTANT:
        value = _require(revision.constant_value, "constant_value", revision)
        return derive(
            value, method.value, f"{value:g}", [Input("constant_value", value)],
            note="entered directly. In the workbook these were written as formulas "
                 "(Rate List - Flats!E16 = '=60'), so they read as calculated cells "
                 "in an audit while actually being inputs (C-33).",
        )

    if method is BuildupMethod.LINK:
        if model is None:
            raise RateBuildupError("LINK rates need the project model to resolve")
        target = revision.links_to_rate_item_id
        if not target:
            raise RateBuildupError(
                f"rate revision {revision.id!r} is a LINK but names no target"
            )
        if target in _seen:
            raise RateBuildupError(
                "circular rate link: " + " -> ".join([*sorted(_seen), target])
            )
        linked = model.current_revision(target)
        if linked is None:
            raise RateBuildupError(f"LINK target {target!r} has no rate revision")
        inner = build_rate(linked, params, model, _seen=_seen | {target})
        return derive(
            inner.value, method.value, f"mirrors {target}",
            [Input("linked_rate", inner.value, target)],
            note="In the workbook rates propagated room-to-room by a daisy chain "
                 "mixing relative and absolute anchors (C-32); the link is now "
                 "explicit and traceable.",
        )

    raise RateBuildupError(f"unhandled build-up method {method!r}")


def effective_rate(item: RateItem, model: ProjectModel, params: ParameterSet) -> Derived:
    """The rate actually used for pricing, honouring any project override.

    A project override is where C-7 goes: two live shuttering rates, Rs 900 and
    Rs 1,086, sitting one sheet apart with nothing saying which is current.
    Here there is one rate and one override, and the override carries a reason
    and an approver.
    """
    for override in model.project_rates:
        if override.rate_item_id == item.id and override.override_value is not None:
            return derive(
                float(override.override_value), "project_override",
                f"{override.override_value:g} (project override)",
                [Input("override_value", override.override_value,
                       override.override_reason or "no reason recorded"),
                 Input("approved_by", override.override_approved_by or "unapproved")],
            )
    revision = model.current_revision(item.id)
    if revision is None:
        raise RateBuildupError(
            f"rate item {item.code!r} has no revision -- MISSING_RATE"
        )
    return build_rate(revision, params, model)
