"""Opening schedules, computed as queries rather than bounded ranges.

The counts were always right here; the money was missing.  ``D&W Schedule``
carries a rate against every type -- Rs 30,000 a fire door, Rs 550/sq.ft of
glazing, Rs 9,500 a running metre of railing -- and nothing was reading column
F, so doors and windows had quantities and no cost.

Pricing them is where the units matter.  A door is bought by the leaf, glazing
by the square metre and railing by the running metre, so the same fold cannot
just multiply: it prices a count against a per-Nos. rate and a measured area
against a per-sq.m rate, through ``units.amount``, which raises rather than
multiplying across dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import OpeningKind, ProjectModel
from ..params import ParameterSet
from ..provenance import Derived, Input, derive
from ..rules.rate_buildup import RateBuildupError, effective_rate
from ..units import Quantity, Rate, UnitConverter, UnitMismatchError, amount


PRICED = "priced"
NO_RATE = "no_rate"
NO_QUANTITY = "no_quantity"
ERROR = "error"


@dataclass(frozen=True)
class ScheduleLine:
    """One line of the opening schedule.

    ``quantity``/``unit`` rather than a bare area, because railings are measured
    in running metres.  The workbook's summary lists BR and UR under "Sq M"
    while their quantities are lengths typed into ``Windows!K`` -- a unit label
    that does not match what is underneath it.
    """

    code: str
    kind: OpeningKind
    width_m: float
    height_m: float
    count: float
    quantity: float
    unit: str
    opening_type_id: str = ""
    #: Set by :func:`priced_opening_schedule`; absent on the bare schedule.
    rate: float | None = None
    rate_unit: str = ""
    rate_item_id: str | None = None
    rate_description: str = ""
    amount: float = 0.0
    status: str = ""
    message: str = ""

    @property
    def area_sqm(self) -> float:
        return self.quantity if self.unit == "SQM" else 0.0

    @property
    def is_priced(self) -> bool:
        return self.status == PRICED


def opening_schedule(model: ProjectModel,
                     kinds: tuple[OpeningKind, ...] | None = None) -> list[ScheduleLine]:
    """Total count and area per opening type, across the whole building.

    ``count`` folds room openings up through the unit types that contain them:
    ``count_in_room x units_of_that_type``.  Nothing is bounded to a range, so
    a new opening type appears in the schedule because it exists, not because
    someone widened ``D146:H149``.
    """
    totals: dict[str, float] = {}
    measures: dict[str, float] = {}
    rooms = {r.id: r for r in model.unit_type_rooms}
    types = {t.id: t for t in model.opening_types}

    for opening in model.room_openings:
        room = rooms.get(opening.unit_type_room_id)
        if room is None:
            continue
        units = model.unit_count(room.unit_type_id)
        multiplier = opening.count * room.count_per_unit * units
        totals[opening.opening_type_id] = totals.get(opening.opening_type_id, 0.0) + multiplier

        opening_type = types.get(opening.opening_type_id)
        if opening_type is None:
            continue
        if opening.linear_qty_m is not None:
            measure = opening.linear_qty_m * multiplier
        elif opening_type.kind is OpeningKind.RAILING:
            measure = 0.0
        else:
            measure = opening_type.area_sqm * multiplier
        measures[opening.opening_type_id] = measures.get(opening.opening_type_id, 0.0) + measure

    lines: list[ScheduleLine] = []
    for opening_type in model.opening_types:
        count = totals.get(opening_type.id, 0.0)
        if kinds is not None and opening_type.kind not in kinds:
            continue
        if not count:
            continue
        unit = "RM" if opening_type.kind is OpeningKind.RAILING else "SQM"
        lines.append(ScheduleLine(
            code=opening_type.code, kind=opening_type.kind,
            width_m=opening_type.width_m, height_m=opening_type.height_m,
            count=count, quantity=measures.get(opening_type.id, 0.0), unit=unit,
            opening_type_id=opening_type.id,
        ))
    return sorted(lines, key=lambda l: l.code)


def total_openings(model: ProjectModel, kinds: tuple[OpeningKind, ...]) -> Derived:
    """How many openings of these kinds the building contains.

    The count and the money come from the same fold, so they cannot disagree the
    way ``Doors!E141`` (58) and ``Doors!L141`` (2,180) do (C-12).
    """
    lines = opening_schedule(model, kinds)
    total = sum(l.count for l in lines)
    return derive(total, "opening_count",
                  f"sum over {len(lines)} opening type(s)",
                  [Input(l.code, l.count) for l in lines],
                  excel_ref="Doors!L141 = SUBTOTAL(9,L5:L140)")


# --------------------------------------------------------------------------
# Pricing the schedule
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleTotal:
    """One band of the opening schedule -- doors, windows, railings."""

    key: str
    label: str
    unit: str
    count: float
    quantity: float
    amount: float
    lines: int
    unpriced: int = 0


#: The bands the schedule reports, in the order a QS reads them.
BANDS: tuple[tuple[str, str, tuple[OpeningKind, ...]], ...] = (
    ("doors", "Doors", (OpeningKind.DOOR,)),
    ("windows", "Windows", (OpeningKind.WINDOW,)),
    ("ventilators", "Ventilators", (OpeningKind.VENTILATOR,)),
    ("railings", "Railings", (OpeningKind.RAILING,)),
    ("curtain_wall", "Curtain wall", (OpeningKind.CURTAIN_WALL,)),
)


def priced_opening_schedule(model: ProjectModel, params: ParameterSet,
                            kinds: tuple[OpeningKind, ...] | None = None
                            ) -> list[ScheduleLine]:
    """The schedule with a rate and an amount against every line.

    What each line is priced *on* follows the rate's own unit: a rate per Nos.
    prices the count, a rate per sq.m or RM prices the measured quantity.  The
    multiplication goes through ``units.amount``, so a per-Nos. rate meeting a
    square-metre quantity raises instead of producing a plausible number.
    """
    converter = UnitConverter(params["factor_sqm_to_sqft"],
                              params["factor_ft_to_rm"])
    items = {i.id: i for i in model.rate_items}
    types = {t.id: t for t in model.opening_types}

    out: list[ScheduleLine] = []
    scheduled: set[str] = set()
    for line in opening_schedule(model, kinds):
        scheduled.add(line.opening_type_id)
        out.append(_price(line, model, params, converter, items, types))

    # A type that carries a rate but reaches no room is work someone priced and
    # nobody measured -- the eight curtain-wall bays are exactly this, Rs 3.30
    # crore in the workbook. Listed at zero rather than left out, so it is a
    # visible gap instead of an absence (C-11's sibling).
    for opening_type in model.opening_types:
        if opening_type.id in scheduled or not opening_type.rate_item_id:
            continue
        if kinds is not None and opening_type.kind not in kinds:
            continue
        out.append(_price(ScheduleLine(
            code=opening_type.code, kind=opening_type.kind,
            width_m=opening_type.width_m, height_m=opening_type.height_m,
            count=0.0, quantity=0.0,
            unit="RM" if opening_type.kind is OpeningKind.RAILING else "SQM",
            opening_type_id=opening_type.id,
        ), model, params, converter, items, types))
    return sorted(out, key=lambda l: (l.kind.value, l.code))


def _price(line: ScheduleLine, model, params, converter, items, types) -> ScheduleLine:
    from dataclasses import replace

    opening_type = types.get(line.opening_type_id)
    item = items.get(opening_type.rate_item_id) if opening_type else None
    if item is None:
        return replace(line, status=NO_RATE,
                       message=f"{line.code} is scheduled but has no rate")

    try:
        rate_derived = effective_rate(item, model, params)
    except RateBuildupError as exc:
        return replace(line, status=NO_RATE, rate_item_id=item.id,
                       rate_description=item.description, message=str(exc))

    revision = model.current_revision(item.id)
    if revision is not None and not revision.is_priced:
        return replace(line, status=NO_RATE, rate_item_id=item.id,
                       rate_description=item.description,
                       message=f"{item.description!r} carries no price")

    rate = Rate.of(rate_derived.value, item.unit)
    # Priced on the count when the rate is per Nos., on the measured quantity
    # otherwise.  Doors are bought by the leaf; glazing by the square metre.
    if rate.per.code == "NOS":
        quantity = Quantity.of(line.count, "NOS")
    else:
        quantity = Quantity.of(line.quantity, line.unit)

    if not quantity.value:
        return replace(line, status=NO_QUANTITY, rate=rate_derived.value,
                       rate_unit=item.unit, rate_item_id=item.id,
                       rate_description=item.description,
                       message=f"{line.code} has a rate but no measured "
                               f"quantity, so it reaches no total")

    try:
        total = amount(quantity, rate, converter)
    except UnitMismatchError as exc:
        return replace(line, status=ERROR, rate=rate_derived.value,
                       rate_unit=item.unit, rate_item_id=item.id,
                       rate_description=item.description, message=str(exc))

    return replace(line, status=PRICED, rate=rate_derived.value,
                   rate_unit=item.unit, rate_item_id=item.id,
                   rate_description=item.description, amount=total)


def opening_totals(model: ProjectModel, params: ParameterSet) -> list[ScheduleTotal]:
    """Doors, windows, railings and curtain wall, each a filter over the fold."""
    lines = priced_opening_schedule(model, params)
    totals: list[ScheduleTotal] = []
    for key, label, kinds in BANDS:
        band = [l for l in lines if l.kind in kinds]
        if not band:
            continue
        units = {l.unit for l in band}
        totals.append(ScheduleTotal(
            key=key, label=label,
            unit=band[0].unit if len(units) == 1 else "",
            count=sum(l.count for l in band),
            quantity=sum(l.quantity for l in band) if len(units) == 1 else 0.0,
            amount=sum(l.amount for l in band),
            lines=len(band),
            unpriced=sum(1 for l in band if not l.is_priced),
        ))
    return totals


def total_opening_amount(model: ProjectModel, params: ParameterSet) -> float:
    """Every door, window, railing and curtain-wall bay in the building."""
    return sum(l.amount for l in priced_opening_schedule(model, params)
               if l.is_priced)
