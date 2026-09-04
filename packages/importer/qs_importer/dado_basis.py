"""Where the dado line sits, and what the wall above it is.

A dado and the wall above it *partition* the height of a room: the tiles take
the lower part and the plaster takes what is left. The workbook measures them
that way --

    Internal Finishes Flats!E46  = D43*D46     dado    perimeter x 2.40
    Internal Finishes Flats!E47  = D43*D47     wall    perimeter x 0.70
                                                       2.40 + 0.70 = 3.10 = D1

-- and this platform does not. It measures the dado at a default height nobody
chose (2.10 m) and then charges the wall for nearly the full height on top, so
the same strip is paid for twice.

Nothing here changes a number. This is the measurement, so that the change can
be decided by somebody who has seen what it does rather than agreed to in
principle. Wall finishes are Rs 6.6 crore of a Rs 22.6 crore take-off, which is
not a rounding matter.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from qs_engine.model import ProjectModel
from qs_engine.params import ParameterSet
from qs_engine.rules.takeoff import compute_takeoff, total_amount

from .mappers.kitchen import (_blocks, _key,
                              counter_measured_room_types)
from .reader import Workbook

#: The take-off blocks, and how far down each sheet they run.
SHEETS: tuple[tuple[str, int], ...] = (("Internal Finishes Flats", 2083),
                                       ("Internal Finishes Offices", 124))

#: The slot whose height the workbook states, and the slot that shares it.
DADO = "dado"
WALL = "wall finishes plaster"


@dataclass
class BasisRow:
    """One room type, measured both ways."""

    room_type: str
    rooms: int
    #: Height per running metre, as each side measures it.
    dado_now: float
    dado_workbook: float
    wall_now: float
    wall_workbook: float
    #: What the difference is worth, at the rates already in the library.
    dado_money: float = 0.0
    wall_money: float = 0.0

    @property
    def partitions(self) -> bool:
        """True when the workbook's two heights add up to the room's height."""
        return abs((self.dado_workbook + self.wall_workbook)
                   - (self.dado_now + self.wall_now)) > 0.01

    @property
    def money(self) -> float:
        return self.dado_money + self.wall_money


@dataclass
class BasisReport:
    rows: list[BasisRow] = field(default_factory=list)
    #: The finishing take-off as it stands, and as it would be.
    total_now: float = 0.0
    total_partitioned: float = 0.0
    #: The workbook's own finishing total, off both of its summaries.
    workbook_total: float = 0.0
    room_types_affected: int = 0
    wall_rows_affected: int = 0

    @property
    def moves_by(self) -> float:
        return self.total_partitioned - self.total_now

    @property
    def gap_now(self) -> float:
        return self.total_now - self.workbook_total

    @property
    def gap_partitioned(self) -> float:
        return self.total_partitioned - self.workbook_total

    @property
    def closer(self) -> bool:
        return abs(self.gap_partitioned) < abs(self.gap_now)


def stated_dado_heights(wb: Workbook, model: ProjectModel) -> dict[str, float]:
    """The dado height the workbook's own formula implies, per room.

    Read off the block that measures that room -- ``E46 / D43`` -- rather than
    parsed out of the formula text, so a block written any other way still
    gives up the number it actually used.
    """
    blocks: dict[tuple, dict] = {}
    for sheet, last in SHEETS:
        try:
            found = _blocks(wb, sheet, last)
        except KeyError:
            continue
        for block in found:
            key = _key(block["area"], block["perimeter"])
            if key is not None:
                blocks.setdefault(key, block)

    heights: dict[str, float] = {}
    for room in model.unit_type_rooms:
        if not room.perimeter_m:
            continue
        block = blocks.get(_key(room.carpet_area_sqm, room.perimeter_m))
        if block is None:
            continue
        row = block["rows"].get(DADO)
        if row is None:
            continue
        gross = wb.number(block["sheet"], f"E{row}")
        if gross:
            heights[room.id] = round(gross / room.perimeter_m, 4)
    return heights


def _partitioned(model: ProjectModel, heights: dict[str, float]
                 ) -> tuple[ProjectModel, int, int]:
    """A copy of the model measured the way the workbook measures it.

    A copy, so that asking the question cannot change the answer to anything
    else -- this runs on the live model and must leave it exactly as it was.
    """
    fresh = copy.deepcopy(model)

    # A kitchen and an office pantry are already right: their dado runs along
    # the counters, not round the perimeter, and their wall already has both
    # dado areas taken off it. Nothing here should reach them -- the question
    # is only about rooms whose dado is a band round the walls.
    counter_measured = counter_measured_room_types(fresh)

    dadoed: set[str] = set()
    for room in fresh.unit_type_rooms:
        height = heights.get(room.id)
        if height is None or room.room_type_id in counter_measured:
            continue
        room.dado_height_m = height
        # A finish schedule hangs off the *pricing* room type, which is not the
        # same as the room's own type: the sizes sheets and the rate list use
        # different vocabularies and the mapping joins them.
        dadoed.add(fresh.pricing_room_type(room.room_type_id)
                   or room.room_type_id)

    slots = {s.id: s for s in fresh.finish_slots}
    switched = 0
    for spec in fresh.room_finish_specs:
        slot = slots.get(spec.finish_slot_id)
        if slot is None or spec.room_type_id not in dadoed:
            continue
        if (spec.qty_rule or slot.qty_rule) != "wall_finish":
            continue
        spec.qty_rule = "wall_above_dado"
        switched += 1
    return fresh, len(dadoed), switched


def workbook_finishing_total(wb: Workbook) -> float:
    """Both finishing summaries, corrected for the duplicate in one of them."""
    flats = ((wb.number("Internal Finishes Flats", "F2040") or 0.0)
             - (wb.number("Internal Finishes Flats", "F2010") or 0.0))
    offices = sum(wb.number("Internal Finishes Offices", f"F{row}") or 0.0
                  for row in range(78, 107))
    return flats + offices


def build_report(model: ProjectModel, params: ParameterSet,
                 wb: Workbook) -> BasisReport:
    """Measure it both ways and say what the difference is worth."""
    heights = stated_dado_heights(wb, model)
    counter_measured = counter_measured_room_types(model)
    other, types, switched = _partitioned(model, heights)

    now = compute_takeoff(model, params)
    then = compute_takeoff(other, params)

    report = BasisReport(
        total_now=total_amount(now), total_partitioned=total_amount(then),
        workbook_total=workbook_finishing_total(wb),
        room_types_affected=types, wall_rows_affected=switched)

    # Per room type: the height each side measures on, and what the gap costs.
    rooms = {r.id: r for r in model.unit_type_rooms}
    shape: dict[str, dict] = {}
    for line in now:
        slot = line.finish_name.lower()
        if slot not in (DADO, WALL):
            continue
        room = rooms.get(line.room_id)
        if (room is None or not room.perimeter_m or room.id not in heights
                or room.room_type_id in counter_measured):
            continue
        entry = shape.setdefault(line.room_type_name, {
            "rooms": set(), DADO: [0.0, 0], WALL: [0.0, 0]})
        entry["rooms"].add(line.room_id)
        entry[slot][0] += line.gross / room.perimeter_m
        entry[slot][1] += 1

    other_rooms = {r.id: r for r in other.unit_type_rooms}
    proposed: dict[str, dict] = {}
    for line in then:
        slot = line.finish_name.lower()
        if slot not in (DADO, WALL):
            continue
        room = other_rooms.get(line.room_id)
        if (room is None or not room.perimeter_m or room.id not in heights
                or room.room_type_id in counter_measured):
            continue
        entry = proposed.setdefault(line.room_type_name,
                                    {DADO: [0.0, 0], WALL: [0.0, 0]})
        entry[slot][0] += line.gross / room.perimeter_m
        entry[slot][1] += 1

    # What the change is worth, per room type. Every line that moved counts,
    # not only the two slots in the table: switching a wall to "above the dado"
    # is applied per *pricing* room type, so a room type that shares a rate
    # block with a dadoed one moves too, and leaving that out of the total
    # would make the rows disagree with the bottom line.
    money: dict[tuple[str, str], float] = {}
    for lines, sign in ((now, -1.0), (then, 1.0)):
        for line in lines:
            if not line.is_priced:
                continue
            slot = line.finish_name.lower()
            key = (line.room_type_name, slot if slot in (DADO, WALL) else WALL)
            money[key] = money.get(key, 0.0) + sign * line.total_amount

    def mean(entry, slot) -> float:
        total, count = entry.get(slot, [0.0, 0])
        return round(total / count, 2) if count else 0.0

    moved = {name for (name, _), value in money.items() if abs(value) > 0.01}
    for name in sorted(shape) + sorted(moved - set(shape)):
        entry = shape.get(name, {"rooms": set()})
        after = proposed.get(name, {})
        row = BasisRow(
            room_type=name, rooms=len(entry.get("rooms", ())),
            dado_now=mean(entry, DADO), dado_workbook=mean(after, DADO),
            wall_now=mean(entry, WALL), wall_workbook=mean(after, WALL),
            dado_money=money.get((name, DADO), 0.0),
            wall_money=money.get((name, WALL), 0.0))
        if abs(row.money) > 0.01 or row.partitions:
            report.rows.append(row)

    report.rows.sort(key=lambda r: -abs(r.money))
    return report
