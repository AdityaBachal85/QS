"""Opening schedules, computed as queries rather than bounded ranges."""

from __future__ import annotations

from dataclasses import dataclass

from ..model import OpeningKind, ProjectModel
from ..params import ParameterSet
from ..provenance import Derived, Input, derive


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

    @property
    def area_sqm(self) -> float:
        return self.quantity if self.unit == "SQM" else 0.0


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
