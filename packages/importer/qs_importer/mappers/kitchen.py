"""Kitchen counters, read out of the take-off blocks.

A kitchen is not measured like other rooms. Its dado runs along the counters,
so the quantity comes from the platform lengths rather than the room perimeter:

    Internal Finishes Flats!E171 = 3.52            main counter, typed
    Internal Finishes Flats!E172 = E171-0.9        service counter, derived
    Internal Finishes Flats!D161 = D1-0.7-0.9      height above the counter
    Internal Finishes Flats!D162 = 0.9             height below it
    Internal Finishes Flats!E161 = (E171+E172)*D161
    Internal Finishes Flats!E162 = (E171+E172)*D162

Those four inputs come across so an imported project arrives measured rather
than blank. The service run imports as its value rather than as ``main - 0.9``:
that relationship is a habit, and an L-shaped service counter does not obey it.
"""

from __future__ import annotations

from qs_engine.model import KitchenPlatform, ProjectModel

from ..ids import IdFactory
from ..reader import Workbook

SHEET = "Internal Finishes Flats"
OFFICE_SHEET = "Internal Finishes Offices"

#: Labels in column B that name each row of a take-off block.
_MAIN = "kitchen platform"
_SERVICE = "service platform"
_DADO_ABOVE = "dado"
_DADO_BELOW = "dado below kitchen platform"

#: The quantity rules that measure off a counter. A room is counter-measured
#: because one of these prices it, never because of what it is called: the
#: office Pantry has a service run and its dado comes off that run
#: (``Internal Finishes Offices!E17 = E26*D17``) exactly as a Kitchen's does,
#: and it is not categorised as a kitchen anywhere (non-negotiable 5).
COUNTER_RULES = frozenset({"kitchen_platform", "service_platform"})


def _blocks(wb: Workbook, sheet: str, last_row: int) -> list[dict]:
    """Every take-off block on a sheet, with the rows that make it up.

    A block starts where column A carries the ``#`` marker. Its head cell
    carries the room name, its carpet area and its perimeter -- which together
    identify which room it measures, without relying on the order either list
    happens to be in.
    """
    blocks: list[dict] = []
    current: dict | None = None
    for row in range(1, last_row + 1):
        if wb.text(sheet, f"A{row}").strip() == "#":
            name = wb.text(sheet, f"B{row}").strip()
            if not name:
                current = None
                continue
            current = {"sheet": sheet, "name": name, "head": row,
                       "area": wb.number(sheet, f"C{row}"),
                       "perimeter": wb.number(sheet, f"D{row}"),
                       "rows": {}}
            blocks.append(current)
            continue
        label = wb.text(sheet, f"B{row}").strip().lower()
        if current is not None and label:
            current["rows"].setdefault(label, row)
    return blocks


def _key(area: float | None, perimeter: float | None) -> tuple | None:
    """A room's dimensions, rounded, as an identity.

    Two decimal places is what the sizes sheet carries, so this matches exactly
    what a QS typed rather than what floating point made of it.
    """
    if area is None or perimeter is None:
        return None
    return (round(float(area), 2), round(float(perimeter), 2))


def map_kitchen_platforms(wb: Workbook, model: ProjectModel,
                          ids: IdFactory) -> list[str]:
    """Give every kitchen its counters, from the block that measures it."""
    warnings: list[str] = []

    counter_measured = counter_measured_room_types(model)
    kitchens = [room for room in model.unit_type_rooms
                if room.room_type_id in counter_measured]
    if not kitchens:
        return warnings

    # Blocks that carry a counter row, indexed by the dimensions of the room
    # they measure. Matching on area and perimeter rather than on position
    # means neither list has to be in any particular order, and a block cannot
    # silently lend its counters to a different kitchen.
    by_dimensions: dict[tuple, dict] = {}
    for sheet, last in ((SHEET, 2083), (OFFICE_SHEET, 124)):
        try:
            found = _blocks(wb, sheet, last)
        except KeyError:
            continue
        for block in found:
            if _MAIN not in block["rows"] and _SERVICE not in block["rows"]:
                continue
            key = _key(block["area"], block["perimeter"])
            if key is not None:
                by_dimensions.setdefault(key, block)

    if not by_dimensions:
        warnings.append(
            "No take-off block carries a Kitchen Platform row, so no counters "
            "were imported. Enter them on the Kitchen platforms tab.")
        return warnings

    unit_codes = {u.id: u.code for u in model.unit_types}

    unmatched: list[str] = []
    for room in kitchens:
        def describe() -> str:
            return (f"{unit_codes.get(room.unit_type_id, '?')} "
                    f"{room.label or room.id} "
                    f"({room.carpet_area_sqm:g} sq m, {room.perimeter_m:g} m)")

        block = by_dimensions.get(_key(room.carpet_area_sqm, room.perimeter_m))
        if block is None:
            unmatched.append(describe())
            continue
        sheet, rows = block["sheet"], block["rows"]

        def number(label: str, column: str) -> float:
            row = rows.get(label)
            return float(wb.number(sheet, f"{column}{row}") or 0.0) if row else 0.0

        main = number(_MAIN, "E")
        service = number(_SERVICE, "E")
        if not main and not service:
            unmatched.append(describe())
            continue
        model.kitchen_platforms.append(KitchenPlatform(
            id=ids.make(room.id, "platform"),
            unit_type_room_id=room.id,
            main_platform_m=main,
            service_platform_m=service,
            dado_above_m=number(_DADO_ABOVE, "D"),
            dado_below_m=number(_DADO_BELOW, "D")))

    if unmatched:
        warnings.append(
            f"{len(unmatched)} room(s) measured off a counter found no take-off "
            f"block of their own size: {'; '.join(unmatched[:4])}"
            + (" ..." if len(unmatched) > 4 else "")
            + ". The workbook has one block for each and applies it to every "
              "unit whatever its size; here they import unmeasured and are "
              "reported, rather than taking their counters from a block that "
              "measures a different room. Enter their runs on the Kitchen "
              "platforms tab -- a counter with no run is not a free one.")
    return warnings


def counter_measured_room_types(model: ProjectModel) -> set[str]:
    """Room types whose finish schedule is measured off a counter.

    Read off the schedule rather than off the room's name or category, so a
    Pantry, a Servant Kitchen or a wet bar all behave the same with no code
    change.
    """
    return {spec.room_type_id for spec in model.room_finish_specs
            if _rule_of(model, spec) in COUNTER_RULES}


def _rule_of(model: ProjectModel, spec) -> str:
    if spec.qty_rule:
        return spec.qty_rule
    for slot in model.finish_slots:
        if slot.id == spec.finish_slot_id:
            return slot.qty_rule
    return ""
