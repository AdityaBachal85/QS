"""Where a value is used -- provenance, run backwards.

Every derived figure already records what it was built from. The question a QS
actually asks is the other one: *if I change this, what moves?* The workbook
cannot answer it at all -- 10.764 is typed into hundreds of formulas and there
is no way to find them -- which is why nobody dares touch a parameter.

This is a fold over the same take-off the money comes from, so an answer here
can never disagree with the figure on screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import ProjectModel
from ..params import ParameterSet
from ..rules.room_qty import HEIGHT_DEPENDENT_RULES, RULE_DEDUCTIONS
from ..rules.takeoff import compute_takeoff


@dataclass
class Use:
    """One place a value is used, and what it is worth there."""

    where: str
    detail: str
    quantity: float = 0.0
    unit: str = ""
    amount: float = 0.0


@dataclass
class Usage:
    subject: str
    kind: str
    description: str = ""
    uses: list[Use] = field(default_factory=list)
    total_amount: float = 0.0
    total_lines: int = 0
    note: str = ""


#: Which parameters feed which quantity rules. Stated once, here, rather than
#: rediscovered by reading every rule -- and asserted by a test, so a rule that
#: starts using a parameter without being listed is caught.
PARAMETER_RULES: dict[str, tuple[str, ...]] = {
    "slab_allowance_m": tuple(sorted(HEIGHT_DEPENDENT_RULES)),
    "default_floor_height_m": tuple(sorted(HEIGHT_DEPENDENT_RULES)),
    "default_dado_height_m": ("dado", "wall_above_dado"),
    "wastage_pct": (),
    "factor_sqm_to_sqft": (),
    "factor_ft_to_rm": (),
    "frame_width_m": (),
}


def parameter_usage(key: str, model: ProjectModel, params: ParameterSet) -> Usage:
    """Every take-off line whose quantity or rate depends on one parameter."""
    parameter = params.values.get(key)
    usage = Usage(subject=key, kind="parameter",
                  description=parameter.description if parameter else "")

    rules = PARAMETER_RULES.get(key)
    lines = compute_takeoff(model, params)

    if rules:
        matched = [l for l in lines if l.qty_rule in rules]
        usage.note = (f"{key} enters the quantity of "
                      f"{', '.join(rules)} in every room that has it.")
    else:
        # Rate-side parameters: find them by name in the rate's own derivation.
        matched = [l for l in lines
                   if l.rate_derivation is not None
                   and any(i.name == key for i in l.rate_derivation.derivation.inputs)]
        usage.note = f"{key} is used building the rate on these lines."

    by_unit: dict[str, Use] = {}
    for line in matched:
        use = by_unit.get(line.unit_type_code)
        if use is None:
            use = Use(where=line.unit_type_code, detail="", unit=line.unit)
            by_unit[line.unit_type_code] = use
        if use.unit != line.unit:
            use.unit = ""
        use.quantity += line.total_qty if use.unit else 0.0
        use.amount += line.total_amount

    for code, use in by_unit.items():
        finishes = sorted({l.finish_name for l in matched if l.unit_type_code == code})
        use.detail = ", ".join(finishes[:4]) + ("…" if len(finishes) > 4 else "")

    usage.uses = sorted(by_unit.values(), key=lambda u: -u.amount)
    usage.total_amount = sum(l.total_amount for l in matched if l.is_priced)
    usage.total_lines = len(matched)
    if not matched:
        # An honest empty answer beats a confident wrong one. Some parameters
        # belong to parts of the estimate that are not built yet -- escalation,
        # contingency and GST apply to the project roll-up, not to a room.
        usage.note = (f"Nothing in the finishing take-off depends on {key} yet. "
                      f"It is declared, and will be used where it belongs.")
    return usage


def rate_usage(rate_item_id: str, model: ProjectModel, params: ParameterSet) -> Usage:
    """Every room priced on one rate, and what it comes to."""
    item = model.rate_item(rate_item_id)
    usage = Usage(subject=rate_item_id, kind="rate",
                  description=f"{item.description} ({item.specification})"
                  if item.specification else item.description)

    matched = [l for l in compute_takeoff(model, params)
               if l.rate_item_id == rate_item_id]
    by_room: dict[str, Use] = {}
    for line in matched:
        key = f"{line.unit_type_code} · {line.room_label}"
        use = by_room.get(key)
        if use is None:
            use = Use(where=key, detail=line.finish_name, unit=line.unit)
            by_room[key] = use
        use.quantity += line.total_qty
        use.amount += line.total_amount

    usage.uses = sorted(by_room.values(), key=lambda u: -u.amount)
    usage.total_amount = sum(l.total_amount for l in matched if l.is_priced)
    usage.total_lines = len(matched)
    usage.note = ("Change this rate and every line here moves. The workbook "
                  "reaches its rates by row offset, so the same question there "
                  "has no answer (C-6).")
    return usage


def room_usage(room_id: str, model: ProjectModel, params: ParameterSet) -> Usage:
    """What one room's area and perimeter drive."""
    room = model.room(room_id)
    usage = Usage(subject=room_id, kind="room", description=room.label)

    matched = [l for l in compute_takeoff(model, params) if l.room_id == room_id]
    usage.uses = [
        Use(where=l.finish_name,
            detail=f"{l.qty_rule}"
                   + (f", less {RULE_DEDUCTIONS.get(l.qty_rule, 'none')}"
                      if l.deduction else ""),
            quantity=l.total_qty, unit=l.unit, amount=l.total_amount)
        for l in sorted(matched, key=lambda l: -l.total_amount)
    ]
    usage.total_amount = sum(l.total_amount for l in matched if l.is_priced)
    usage.total_lines = len(matched)
    usage.note = ("Its carpet area and perimeter are the only inputs; "
                  "everything here is computed from them.")
    return usage
