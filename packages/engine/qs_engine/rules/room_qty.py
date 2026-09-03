"""Room quantity rules and the deduction rules that go with them.

This is the module that replaces the workbook's 1,451 hand-written take-off
rows.  In ``Internal Finishes Flats`` each room block is written out by hand:

    E5 = C4                                 floor area
    E6 = D4                                 skirting = perimeter
    E8 = D4*(D1-0.15)                       wall = perimeter x (height - slab)
    F6 = -(Doors!H5+Doors!H6+Doors!H7+Doors!H9)     deduction, HAND-PICKED

That last line is the problem the platform exists to solve, and it fails twice
over:

* **It is a hand-picked list of cell addresses.**  ``Doors!H8`` is in the range
  but not in the formula, and nothing records whether that was deliberate
  (C-13).  Repeated ~150 times, each block picking its own set.
* **It deducts the wrong thing.**  ``Doors!H`` is the *area* column, width x
  height in sq.m, and it is being subtracted from a skirting quantity in
  running metres.  Every door is 2.1 m high, so the deduction is exactly 2.1x
  too large.  Across 52 skirting rows with unit counts applied, 1,448.23 RM of
  skirting is over-deducted and never priced: Rs 5,67,648 (C-35).

Here a deduction is a rule evaluated over the room's actual openings, carrying
the same unit as the quantity it reduces.  Add a door to a room and every
affected quantity moves by itself; deduct an area from a length and the engine
raises instead of computing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..model import (OpeningKind, OpeningType, ProjectModel, RoomOpening,
                     UnitTypeRoom)
from ..params import ParameterSet
from ..provenance import Derived, Input, derive
from ..units import Quantity, UnitConverter, UnitMismatchError


class QtyRuleError(Exception):
    """Raised when a quantity rule cannot be evaluated as configured."""


class NegativeNetQuantityError(Exception):
    """Deductions exceed the gross quantity.

    Excel adds a negative number -- ``G = E + F`` where ``F`` is already
    negative -- so an over-deduction simply flows through into the cost.  Here
    it stops.
    """


# --------------------------------------------------------------------------
# Frame run -- how much frame one opening needs
# --------------------------------------------------------------------------

def frame_run_perimeter_full(op: OpeningType) -> tuple[float, str]:
    """``2 x (W + H)`` -- the full opening perimeter.

    This is what the workbook does for windows:
    ``Internal Finishes Flats!E14 = Windows!F4*2 + Windows!G4*2``.
    """
    return 2 * (op.width_m + op.height_m), f"2 x ({op.width_m:g} + {op.height_m:g})"


def frame_run_jambs_and_head(op: OpeningType) -> tuple[float, str]:
    """``2H + W`` -- two jambs and a head, no sill.  Standard for doors."""
    return 2 * op.height_m + op.width_m, f"2 x {op.height_m:g} + {op.width_m:g}"


FRAME_RUN_RULES: dict[str, Callable[[OpeningType], tuple[float, str]]] = {
    "perimeter_full": frame_run_perimeter_full,
    "jambs_and_head": frame_run_jambs_and_head,
}

#: Q-8, open.  The workbook computes the full perimeter for window frames.
#: Doors conventionally take jambs and head only.  The workbook's behaviour is
#: the default so nothing changes silently; a QS decision flips it.
DEFAULT_FRAME_RUN_RULE: dict[OpeningKind, str] = {
    OpeningKind.DOOR: "perimeter_full",
    OpeningKind.WINDOW: "perimeter_full",
    OpeningKind.VENTILATOR: "perimeter_full",
    OpeningKind.RAILING: "perimeter_full",
    OpeningKind.CURTAIN_WALL: "perimeter_full",
}


# --------------------------------------------------------------------------
# Deduction rules
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DeductionRule:
    """What a finish deducts for each opening in the room.

    ``measure`` returns a :class:`Quantity`, so it carries a unit.  If that unit
    is not compatible with the gross quantity's unit, applying the deduction
    raises -- which is the mechanism that makes C-35 impossible.
    """

    code: str
    description: str
    kinds: tuple[OpeningKind, ...]
    measure: Callable[[OpeningType, ParameterSet], Quantity]


def _door_width(op: OpeningType, _p: ParameterSet) -> Quantity:
    return Quantity.of(op.width_m, "RM")


def _opening_area(op: OpeningType, _p: ParameterSet) -> Quantity:
    return Quantity.of(op.area_sqm, "SQM")


def _opening_area_within_dado(op: OpeningType, params: ParameterSet) -> Quantity:
    """Only the part of the opening that falls below the dado line."""
    dado = params.get("default_dado_height_m", 2.1) or 2.1
    return Quantity.of(op.width_m * min(op.height_m, dado), "SQM")


DEDUCTION_RULES: dict[str, DeductionRule] = {
    "door_width": DeductionRule(
        "door_width",
        "Skirting is interrupted by the width of each door opening. A linear "
        "quantity deducts a linear measure -- not the door's area (C-35).",
        (OpeningKind.DOOR,), _door_width),
    "door_and_window_area": DeductionRule(
        "door_and_window_area",
        "Wall finishes deduct the full area of every door and window opening.",
        (OpeningKind.DOOR, OpeningKind.WINDOW, OpeningKind.VENTILATOR,
         OpeningKind.CURTAIN_WALL), _opening_area),
    "openings_within_dado": DeductionRule(
        "openings_within_dado",
        "Dado deducts only the part of each opening below the dado line.",
        (OpeningKind.DOOR, OpeningKind.WINDOW, OpeningKind.VENTILATOR),
        _opening_area_within_dado),
    "none": DeductionRule("none", "Nothing is deducted.", (), _opening_area),
}


def compute_deduction(room: UnitTypeRoom, rule_code: str, model: ProjectModel,
                      params: ParameterSet, target_unit: str) -> Derived:
    """Sum a deduction over every opening actually present in the room.

    There is no list of cell addresses to forget a door from: the deduction is
    a fold over ``model.openings_of(room.id)``.
    """
    rule = DEDUCTION_RULES.get(rule_code)
    if rule is None:
        raise QtyRuleError(f"unknown deduction rule {rule_code!r}")

    total = Quantity.of(0.0, target_unit)
    inputs: list[Input] = []
    if rule.code == "none":
        return derive(total, "deduction:none", "0", [])

    for opening in model.openings_of(room.id):
        op_type = model.opening_type(opening.opening_type_id)
        if op_type.kind not in rule.kinds:
            continue
        measure = rule.measure(op_type, params)
        try:
            contribution = measure.scale(opening.count)
            total = total.add(contribution)
        except UnitMismatchError as exc:
            raise UnitMismatchError(
                f"{rule.code} on room {room.label or room.id!r}: {exc}. "
                f"A deduction must carry the same dimension as the quantity it "
                f"reduces -- this is defect C-35."
            ) from exc
        inputs.append(Input(
            f"{op_type.code} x {opening.count:g}",
            contribution.value,
            f"{op_type.width_m:g} x {op_type.height_m:g} m {op_type.kind.value}",
        ))

    return derive(total, f"deduction:{rule.code}",
                  f"sum over {len(inputs)} opening(s) in this room",
                  inputs, note=rule.description)


# --------------------------------------------------------------------------
# Gross quantity rules
# --------------------------------------------------------------------------

def _clear_height(room: UnitTypeRoom, params: ParameterSet,
                  floor_height_m: float | None = None) -> tuple[float, str]:
    """The floor-to-floor height to measure this room's walls against.

    Most specific wins:

    1. the room's own ``clear_height_m`` -- a double-height gym overrides
       everything below it;
    2. **the height of the floor the unit actually sits on**, from Room Config;
    3. the project parameter, only when the unit sits on no floor at all.

    Step 2 is the one the workbook does not have.  ``Internal Finishes Flats!D1``
    is 3.1, hard-coded once per take-off block, so every Ground Floor wall is
    measured 1.1 m short and the Terrace 3.35 m short.  Returning the source
    alongside the value keeps that visible in the derivation panel.
    """
    if room.clear_height_m is not None:
        return room.clear_height_m, "room"
    if floor_height_m is not None:
        return floor_height_m, "floor"
    return (params.get("default_floor_height_m", 3.1) or 3.1), "parameter"


def _dado_height(room: UnitTypeRoom, params: ParameterSet) -> float:
    if room.dado_height_m is not None:
        return room.dado_height_m
    return params.get("default_dado_height_m", 2.1) or 2.1


def qty_floor_area(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
                   floor_height_m: float | None = None) -> Derived:
    return derive(Quantity.of(room.carpet_area_sqm, "SQM"), "floor_area",
                  f"carpet area = {room.carpet_area_sqm:g}",
                  [Input("carpet_area_sqm", room.carpet_area_sqm)],
                  excel_ref="Internal Finishes Flats!E5 = C4")


def qty_ceiling_area(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
                     floor_height_m: float | None = None) -> Derived:
    return derive(Quantity.of(room.carpet_area_sqm, "SQM"), "ceiling_area",
                  f"carpet area = {room.carpet_area_sqm:g}",
                  [Input("carpet_area_sqm", room.carpet_area_sqm)],
                  excel_ref="Internal Finishes Flats!E9 = E5")


def qty_skirting(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
                 floor_height_m: float | None = None) -> Derived:
    return derive(Quantity.of(room.perimeter_m, "RM"), "skirting",
                  f"perimeter = {room.perimeter_m:g}",
                  [Input("perimeter_m", room.perimeter_m)],
                  excel_ref="Internal Finishes Flats!E6 = D4")


def qty_wall_finish(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
                    floor_height_m: float | None = None) -> Derived:
    """Wall area = room perimeter x clear height.

    Clear height is the floor-to-floor height from Room Config less the slab.
    Both come from named places: the height from the floor this unit sits on,
    the 0.15 from ``slab_allowance_m``.
    """
    height, source = _clear_height(room, params, floor_height_m)
    slab = params["slab_allowance_m"]
    value = room.perimeter_m * (height - slab)
    return derive(Quantity.of(value, "SQM"), "wall_finish",
                  f"{room.perimeter_m:g} x ({height:g} - {slab:g})",
                  [Input("perimeter_m", room.perimeter_m),
                   Input("floor_to_floor_ht", height, source),
                   Input("slab_allowance_m", slab, "parameter")],
                  excel_ref="Internal Finishes Flats!E8 = D4*(D1-0.15)",
                  note=f"height taken from the {source}")


def qty_dado(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
             floor_height_m: float | None = None) -> Derived:
    dado = _dado_height(room, params)
    value = room.perimeter_m * dado
    return derive(Quantity.of(value, "SQM"), "dado",
                  f"{room.perimeter_m:g} x {dado:g}",
                  [Input("perimeter_m", room.perimeter_m), Input("dado_height_m", dado)],
                  excel_ref="Internal Finishes Flats!E59 = D56*D59")


def qty_wall_above_dado(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
                        floor_height_m: float | None = None) -> Derived:
    height, source = _clear_height(room, params, floor_height_m)
    dado = _dado_height(room, params)
    value = room.perimeter_m * (height - dado)
    return derive(Quantity.of(value, "SQM"), "wall_above_dado",
                  f"{room.perimeter_m:g} x ({height:g} - {dado:g})",
                  [Input("perimeter_m", room.perimeter_m),
                   Input("floor_to_floor_ht", height, source),
                   Input("dado_height_m", dado)])


def _frame_qty(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
               kinds: tuple[OpeningKind, ...], rule_name: str) -> Derived:
    total = 0.0
    inputs: list[Input] = []
    for opening in model.openings_of(room.id):
        op_type = model.opening_type(opening.opening_type_id)
        if op_type.kind not in kinds:
            continue
        rule_code = DEFAULT_FRAME_RUN_RULE.get(op_type.kind, "perimeter_full")
        run, expr = FRAME_RUN_RULES[rule_code](op_type)
        contribution = run * opening.count
        total += contribution
        inputs.append(Input(f"{op_type.code} x {opening.count:g}", contribution,
                            f"{expr} [{rule_code}]"))
    return derive(Quantity.of(total, "RM"), rule_name,
                  f"sum of frame runs over {len(inputs)} opening(s)", inputs,
                  note="Frame run rule is configurable per opening kind; the "
                       "workbook's full-perimeter behaviour is the default "
                       "pending Q-8.")


def qty_door_frame(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
                   floor_height_m: float | None = None) -> Derived:
    return _frame_qty(room, model, params, (OpeningKind.DOOR,), "door_frame")


def qty_window_frame(room: UnitTypeRoom, model: ProjectModel, params: ParameterSet,
                     floor_height_m: float | None = None) -> Derived:
    return _frame_qty(room, model, params,
                      (OpeningKind.WINDOW, OpeningKind.VENTILATOR), "window_frame")


QTY_RULES: dict[str, Callable[..., Derived]] = {
    "floor_area": qty_floor_area,
    "ceiling_area": qty_ceiling_area,
    "skirting": qty_skirting,
    "wall_finish": qty_wall_finish,
    "dado": qty_dado,
    "wall_above_dado": qty_wall_above_dado,
    "door_frame": qty_door_frame,
    "window_frame": qty_window_frame,
}

#: The rules whose quantity depends on the floor-to-floor height.  Flooring,
#: ceiling and skirting do not appear here, so a unit type spanning two
#: heights yields one line for those and two for these.
HEIGHT_DEPENDENT_RULES: frozenset[str] = frozenset(
    {"wall_finish", "wall_above_dado"})

#: Which deduction each quantity rule applies.  This is the table that was
#: previously ~150 hand-written formulas.
RULE_DEDUCTIONS: dict[str, str] = {
    "floor_area": "none",
    "ceiling_area": "none",
    "skirting": "door_width",
    "wall_finish": "door_and_window_area",
    "dado": "openings_within_dado",
    "wall_above_dado": "none",
    "door_frame": "none",
    "window_frame": "none",
}


@dataclass(frozen=True)
class RoomQuantity:
    """Gross, deduction and net for one finish in one room -- all unit-safe."""

    room_id: str
    rule: str
    gross: Quantity
    deduction: Quantity
    net: Quantity
    gross_derivation: Derived
    deduction_derivation: Derived


def compute_room_quantity(room: UnitTypeRoom, rule_code: str, model: ProjectModel,
                          params: ParameterSet,
                          converter: UnitConverter | None = None,
                          floor_height_m: float | None = None) -> RoomQuantity:
    """Gross minus deduction for one finish in one room.

    ``net = gross - deduction`` with the deduction positive, rather than Excel's
    ``G = E + F`` with ``F`` already negative.  The difference matters: an
    over-deduction here raises, where Excel's just flows through.
    """
    rule = QTY_RULES.get(rule_code)
    if rule is None:
        raise QtyRuleError(f"unknown quantity rule {rule_code!r}")

    gross_d = rule(room, model, params, floor_height_m)
    gross: Quantity = gross_d.value
    deduction_d = compute_deduction(room, RULE_DEDUCTIONS.get(rule_code, "none"),
                                    model, params, gross.unit.code)
    deduction: Quantity = deduction_d.value

    net = gross.subtract(deduction, converter)
    if net.value < 0:
        raise NegativeNetQuantityError(
            f"room {room.label or room.id!r}, {rule_code}: deductions "
            f"({deduction}) exceed gross ({gross}). NEGATIVE_NET_QTY."
        )
    return RoomQuantity(room.id, rule_code, gross, deduction, net, gross_d, deduction_d)
