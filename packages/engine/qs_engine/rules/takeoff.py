"""The finishing take-off: quantities meet rates, and rupees appear.

This replaces ``Internal Finishes Flats`` -- 1,451 hand-written take-off rows
and 9,472 formulas, one block per room, each block re-anchored to the rate list
by a hand-counted row offset.

Here it is a fold. For every unit type, every room in it, and every finish that
applies to that room's type: compute the quantity with its deduction, resolve
the rate by identity, multiply by how many of that unit the building has. No
new arithmetic is invented -- this composes ``compute_room_quantity``,
``effective_rate`` and ``amount``, each already tested against the workbook.

Three things the workbook could not do fall out of it:

* A finish that has a quantity and no rate is a **priced-at-nothing** line, not
  a zero. ``Cost Sheet Tower!I99`` shows Rs 0 against 4,508.24 sq.m of measured
  false ceiling while the cell beside it works out Rs 65.5 lakh (C-11).
* A line whose quantity and rate disagree on dimension **raises** rather than
  computing (C-35).
* Every line carries its provenance, so any figure opens into the working.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import ProjectModel, UnitTypeRoom
from ..params import ParameterSet
from ..provenance import Derived
from ..rules.rate_buildup import RateBuildupError, effective_rate
from ..rules.room_qty import (NegativeNetQuantityError, QtyRuleError,
                              compute_room_quantity)
from ..units import Quantity, Rate, UnitConverter, UnitMismatchError, amount


class LineStatus:
    PRICED = "priced"
    NO_RATE = "no_rate"
    NO_RULE = "no_rule"
    ERROR = "error"


@dataclass
class TakeoffLine:
    """One finish, in one room, of one unit type."""

    unit_type_id: str
    unit_type_code: str
    room_id: str
    room_label: str
    room_type_id: str
    finish_slot_id: str
    finish_name: str
    qty_rule: str
    unit: str
    gross: float
    deduction: float
    net: float
    unit_count: int
    total_qty: float
    rate_item_id: str | None
    rate_description: str
    rate: float | None
    amount_per_unit: float
    total_amount: float
    status: str
    message: str = ""
    #: Kept so the derivation panel can show the working behind any figure.
    gross_derivation: Derived | None = field(default=None, repr=False)
    deduction_derivation: Derived | None = field(default=None, repr=False)
    rate_derivation: Derived | None = field(default=None, repr=False)

    @property
    def is_priced(self) -> bool:
        return self.status == LineStatus.PRICED


def compute_takeoff(model: ProjectModel, params: ParameterSet,
                    unit_type_id: str | None = None) -> list[TakeoffLine]:
    """Every priced finish in the project, or in one unit type."""
    converter = UnitConverter(params["factor_sqm_to_sqft"],
                              params["factor_ft_to_rm"])
    slots = {s.id: s for s in model.finish_slots}
    rate_items = {r.id: r for r in model.rate_items}

    lines: list[TakeoffLine] = []
    unit_types = ([model.unit_type(unit_type_id)] if unit_type_id
                  else sorted(model.unit_types, key=lambda u: u.seq))

    for unit in unit_types:
        count = model.unit_count(unit.id)
        for room in model.rooms_of(unit.id):
            for spec in model.finish_spec_for(room.room_type_id):
                slot = slots.get(spec.finish_slot_id)
                if slot is None:
                    continue
                rule = spec.qty_rule or slot.qty_rule
                lines.append(_line(model, params, converter, unit, count, room,
                                   spec, slot, rule, rate_items))
    return lines


def _line(model, params, converter, unit, count, room: UnitTypeRoom,
          spec, slot, rule, rate_items) -> TakeoffLine:
    base = dict(
        unit_type_id=unit.id, unit_type_code=unit.code,
        room_id=room.id, room_label=room.label, room_type_id=room.room_type_id,
        finish_slot_id=slot.id, finish_name=slot.name, qty_rule=rule or "",
        unit="", gross=0.0, deduction=0.0, net=0.0,
        unit_count=count, total_qty=0.0,
        rate_item_id=spec.rate_item_id, rate_description="", rate=None,
        amount_per_unit=0.0, total_amount=0.0, status=LineStatus.ERROR,
    )

    if not rule:
        return TakeoffLine(**{**base, "status": LineStatus.NO_RULE,
                              "message": f"{slot.name} has no quantity rule"})

    try:
        quantity = compute_room_quantity(room, rule, model, params, converter)
    except (QtyRuleError, NegativeNetQuantityError, UnitMismatchError) as exc:
        return TakeoffLine(**{**base, "status": LineStatus.ERROR,
                              "message": str(exc)})

    net: Quantity = quantity.net
    total_qty = net.value * room.count_per_unit * count
    base.update(unit=net.unit.code, gross=quantity.gross.value,
                deduction=quantity.deduction.value, net=net.value,
                total_qty=total_qty,
                gross_derivation=quantity.gross_derivation,
                deduction_derivation=quantity.deduction_derivation)

    item = rate_items.get(spec.rate_item_id) if spec.rate_item_id else None
    if item is None:
        return TakeoffLine(**{**base, "status": LineStatus.NO_RATE,
                              "message": f"{slot.name} in {room.label} is "
                                         f"measured but has no rate"})
    base["rate_description"] = item.description

    try:
        rate_derived = effective_rate(item, model, params)
    except RateBuildupError as exc:
        return TakeoffLine(**{**base, "status": LineStatus.NO_RATE,
                              "message": str(exc)})

    revision = model.current_revision(item.id)
    if revision is not None and not revision.is_priced:
        return TakeoffLine(**{
            **base, "status": LineStatus.NO_RATE, "rate": None,
            "rate_derivation": rate_derived,
            "message": f"{item.description!r} has no price. This is measured "
                       f"work showing nothing, not work that costs nothing."})

    try:
        per_unit = amount(net, Rate.of(rate_derived.value, item.unit), converter)
    except UnitMismatchError as exc:
        return TakeoffLine(**{**base, "status": LineStatus.ERROR,
                              "rate": rate_derived.value,
                              "message": str(exc)})

    return TakeoffLine(**{
        **base, "rate": rate_derived.value, "rate_derivation": rate_derived,
        "amount_per_unit": per_unit * room.count_per_unit,
        "total_amount": per_unit * room.count_per_unit * count,
        "status": LineStatus.PRICED})


# --------------------------------------------------------------------------
# Aggregation -- filters, never ranges
# --------------------------------------------------------------------------

@dataclass
class Group:
    key: str
    label: str
    unit: str
    quantity: float
    amount: float
    lines: int
    unpriced: int = 0

    @property
    def blended_rate(self) -> float | None:
        """Amount over quantity.

        The workbook's cost sheet is priced on exactly this figure --
        ``Internal Finishes Flats!E1998 = IF(D1998=0,0,F1998/D1998)`` -- a
        weighted average that exists nowhere in the rate list. It is shown
        here as what it is, beside the master rates, rather than standing in
        for them (C-6).
        """
        return self.amount / self.quantity if self.quantity else None


def by_finish(lines: list[TakeoffLine]) -> list[Group]:
    """Totals per finish slot, across the whole project."""
    return _group(lines, lambda l: (l.finish_slot_id, l.finish_name))


def by_unit_type(lines: list[TakeoffLine]) -> list[Group]:
    return _group(lines, lambda l: (l.unit_type_id, l.unit_type_code))


def by_room(lines: list[TakeoffLine]) -> list[Group]:
    return _group(lines, lambda l: (l.room_id, l.room_label))


def _group(lines: list[TakeoffLine], key) -> list[Group]:
    groups: dict[str, Group] = {}
    for line in lines:
        group_key, label = key(line)
        group = groups.get(group_key)
        if group is None:
            group = Group(group_key, label, line.unit, 0.0, 0.0, 0)
            groups[group_key] = group
        # Quantities only add up within one unit; a group spanning units
        # reports the money and leaves the quantity blank rather than summing
        # square metres and running metres together.
        if group.unit and group.unit != line.unit:
            group.unit = ""
        group.quantity += line.total_qty if group.unit else 0.0
        group.amount += line.total_amount
        group.lines += 1
        if not line.is_priced:
            group.unpriced += 1
    return sorted(groups.values(), key=lambda g: -g.amount)


def total_amount(lines: list[TakeoffLine]) -> float:
    """The project's finishing cost. A filter, never ``SUM(I39:I99)``."""
    return sum(l.total_amount for l in lines if l.is_priced)


def unpriced(lines: list[TakeoffLine]) -> list[TakeoffLine]:
    """Measured work that reaches no total -- the C-11 class, made visible."""
    return [l for l in lines if l.status == LineStatus.NO_RATE and l.total_qty]
