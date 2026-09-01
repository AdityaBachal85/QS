"""D&W Schedule / Doors / Windows -> opening types and room openings.

Three sheets collapse into two tables.

``D&W Schedule`` is the type master: code, length, height, rate.  It becomes
``opening_type``, with ``area_sqm`` derived from width x height rather than
stored in a Quantity column.

``Doors`` and ``Windows`` are the same structure twice, each a stack of blocks
keyed to a unit type, each row an opening in a room.  They become
``room_opening`` -- an opening attached to the room it sits in.  That single
change is what lets deductions become a rule: the workbook's
``-(Doors!H5+Doors!H6+Doors!H7+Doors!H9)`` is a hand-picked list of cell
addresses, and here the same deduction is a fold over the room's own openings.

The schedule totals also stop being range-bound.  ``Cost Sheet Tower``'s
VLOOKUPs reach into ``Doors!D146:H149`` (four door types) and
``Windows!D166:H177`` (twelve), so a fifth door type returns ``#N/A`` or is
silently dropped (C-18).  Here the schedule is a query and has no bound.

One number is *not* carried across as written: ``Doors!E141``, labelled "Total
Doors", is ``SUBTOTAL(9,E67:E140)`` = 58, while every other total on the same
row starts at row 5 and ``L141`` reports 2,180.  It counts the back half of the
schedule (C-12).  The platform computes the count the same way it computes the
money, so the two cannot disagree.
"""

from __future__ import annotations

import re

from qs_engine.model import OpeningKind, OpeningType, ProjectModel, RoomOpening

from ..ids import IdFactory
from ..reader import Workbook
from .unit_sizes import normalise_type_name

SCHEDULE_SHEET = "D&W Schedule"
SCHEDULE_FIRST_ROW, SCHEDULE_LAST_ROW = 4, 20
CURTAIN_FIRST_ROW, CURTAIN_LAST_ROW = 23, 30

_KIND_PATTERNS: tuple[tuple[str, OpeningKind], ...] = (
    (r"^CURTAIN", OpeningKind.CURTAIN_WALL),
    (r"^OFFICE\s*\d+$", OpeningKind.CURTAIN_WALL),
    (r"FRD$", OpeningKind.DOOR),
    (r"^D\d", OpeningKind.DOOR),
    (r"^V$", OpeningKind.VENTILATOR),
    (r"^(BR|UR)", OpeningKind.RAILING),
    (r"^W", OpeningKind.WINDOW),
    (r"^(SW|LW)$", OpeningKind.WINDOW),
)


def classify_opening(code: str) -> OpeningKind:
    text = " ".join(str(code).split()).upper()
    for pattern, kind in _KIND_PATTERNS:
        if re.search(pattern, text):
            return kind
    return OpeningKind.WINDOW


def map_opening_types(wb: Workbook, model: ProjectModel, ids: IdFactory) -> ProjectModel:
    """Read the type master, including the eight curtain-wall bays."""
    for row in range(SCHEDULE_FIRST_ROW, SCHEDULE_LAST_ROW + 1):
        code = wb.text(SCHEDULE_SHEET, f"B{row}")
        if not code:
            continue
        for part in [c.strip() for c in code.split("/") if c.strip()]:
            # "BR/UR" is one schedule row but two codes in the take-off, and the
            # window summary lists them separately. Split so both resolve.
            model.opening_types.append(OpeningType(
                id=ids.make(model.project.id, "op", part),
                project_id=model.project.id,
                code=part,
                kind=classify_opening(part),
                width_m=float(wb.number(SCHEDULE_SHEET, f"C{row}", 0.0) or 0.0),
                height_m=float(wb.number(SCHEDULE_SHEET, f"D{row}", 0.0) or 0.0),
                specification=f"{SCHEDULE_SHEET}!B{row}",
            ))

    for row in range(CURTAIN_FIRST_ROW, CURTAIN_LAST_ROW + 1):
        label = wb.text(SCHEDULE_SHEET, f"B{row}")
        if not label:
            continue
        model.opening_types.append(OpeningType(
            id=ids.make(model.project.id, "op", "cw", label),
            project_id=model.project.id,
            code=f"CW {label}",
            kind=OpeningKind.CURTAIN_WALL,
            width_m=float(wb.number(SCHEDULE_SHEET, f"C{row}", 0.0) or 0.0),
            height_m=float(wb.number(SCHEDULE_SHEET, f"D{row}", 0.0) or 0.0),
            specification=f"Curtain wall bay, {SCHEDULE_SHEET}!B{row}",
        ))
    return model


def _opening_type_index(model: ProjectModel) -> dict[str, OpeningType]:
    return {ot.code.strip().upper(): ot for ot in model.opening_types}


#: Section headers in the take-off that stand for a *group* of unit types.
#: ``Doors!B129`` "Office Doors" carries ``K129 = SUM('Room Conf'!D40:K40)`` = 32
#: and three rows beneath it, standing in for all eight office types at once.
_GROUP_HEADERS: dict[str, str] = {"office doors": "Office"}

#: Room names used in the door schedule that differ from the names in the sizes
#: sheet.  Attaching by alias is what turns a flat "x32" into openings on real
#: rooms, so the deduction rules can see them.
_ROOM_ALIASES: dict[str, tuple[str, ...]] = {
    "main door": ("office",),
    "panty door": ("pantry",),
    "toilet": ("wc", "w.c", "toilet"),
    "entrance door": ("office", "living, dining"),
}


def _resolve_rooms(label: str, unit_types, model: ProjectModel) -> list[str]:
    """Room ids matching ``label`` across the block's unit type(s)."""
    key = " ".join(str(label).split()).strip().lower()
    candidates = [key, *(_ROOM_ALIASES.get(key, ()))]
    found: list[str] = []
    for unit_type in unit_types:
        for room in model.rooms_of(unit_type.id):
            if room.label.strip().lower() in candidates:
                found.append(room.id)
                break
    return found


def map_schedule_sheet(wb: Workbook, model: ProjectModel, ids: IdFactory,
                       sheet: str, first_row: int, last_row: int,
                       *, label_col: str = "B", type_col: str = "C",
                       nos_col: str = "E", count_col: str = "K") -> tuple[int, list[str]]:
    """Read one take-off schedule (Doors or Windows) into ``room_opening`` rows.

    Blocks are found by matching column B against known unit-type names, so the
    one-row offset between the two sheets -- ``Doors!B5`` points at
    ``'Flat Sizes'!B5`` while ``Windows!B4`` points at ``'Flat Sizes'!B5`` --
    needs no special-casing.

    Three shapes of row are handled, because the workbook uses all three:

    1. a block header naming one unit type, followed by its rooms;
    2. a group header ("Office Doors") standing for every office type at once;
    3. a self-contained common-area row that is its own single-room entity and
       carries its own count in column K -- often typed, with no formula
       (``Doors!K137`` = 37).

    Returns (rows mapped, warnings).
    """
    by_type_name = {normalise_type_name(ut.code).lower(): ut for ut in model.unit_types}
    openings = _opening_type_index(model)
    warnings: list[str] = []
    mapped = 0
    current: list = []

    last_rooms: list[str] = []
    for row in range(first_row, last_row + 1):
        label = wb.text(sheet, f"{label_col}{row}")
        code_here = wb.text(sheet, f"{type_col}{row}")
        if not label and code_here and last_rooms:
            # A blank room name under a filled one means "same room again" --
            # a second window in the same bedroom. Six W4A rows are written
            # this way (Windows!B42, B53, B66, B77, B115, B128), 248.02 sq.m in
            # total. Reading them as unattached would drop them from every
            # deduction, overstating those rooms' wall finishes by that area.
            warnings.append(
                f"{sheet}!{label_col}{row}: no room name; opening {code_here!r} "
                f"read as belonging to the room above. Implicit in the workbook, "
                f"explicit here."
            )
            _attach(model, ids, last_rooms, openings, code_here, wb, sheet, row,
                    nos_col, count_col, warnings)
            mapped += 1
            continue
        if not label:
            continue
        name = " ".join(label.split())
        key = normalise_type_name(name).lower()
        code = wb.text(sheet, f"{type_col}{row}")

        if not code:
            if key in _GROUP_HEADERS:
                wanted = _GROUP_HEADERS[key]
                current = [u for u in model.unit_types if u.classification == wanted]
            elif key in by_type_name:
                current = [by_type_name[key]]
            continue

        opening_type = openings.get(code.strip().upper())
        if opening_type is None:
            warnings.append(
                f"{sheet}!{type_col}{row}: opening code {code!r} is not in "
                f"{SCHEDULE_SHEET} -- it has no dimensions or rate"
            )
            continue

        room_ids = _resolve_rooms(name, current, model)
        if not room_ids and key in by_type_name:
            # A single-room common-area entity listed inline.
            rooms = model.rooms_of(by_type_name[key].id)
            room_ids = [rooms[0].id] if rooms else []
        if not room_ids:
            room_ids = _create_orphan_room(wb, sheet, row, name, model, ids,
                                           count_col, warnings)
        if not room_ids:
            warnings.append(
                f"{sheet}!{label_col}{row}: {name!r} matches no room; "
                f"opening {code!r} not attached"
            )
            continue

        last_rooms = room_ids
        _attach(model, ids, room_ids, openings, code, wb, sheet, row,
                nos_col, count_col, warnings)
        mapped += len(room_ids)
    return mapped, warnings


def _attach(model: ProjectModel, ids: IdFactory, room_ids: list[str],
            openings: dict[str, OpeningType], code: str, wb: Workbook,
            sheet: str, row: int, nos_col: str, count_col: str,
            warnings: list[str]) -> None:
    """Create the room_opening rows for one schedule line."""
    opening_type = openings.get(code.strip().upper())
    if opening_type is None:
        return
    count = wb.number(sheet, f"{nos_col}{row}", 1.0) or 1.0
    run: float | None = None
    if opening_type.kind is OpeningKind.RAILING:
        # Railings carry a typed run rather than dimensions.
        run = wb.number(sheet, "K" + str(row))
        if run is None:
            warnings.append(
                f"{sheet}!K{row}: railing {code!r} has no run length; it will "
                f"price at zero"
            )
    for room_id in room_ids:
        model.room_openings.append(RoomOpening(
            id=ids.make(room_id, opening_type.id, row),
            unit_type_room_id=room_id,
            opening_type_id=opening_type.id,
            count=float(count),
            linear_qty_m=run,
        ))


def _create_orphan_room(wb: Workbook, sheet: str, row: int, name: str,
                        model: ProjectModel, ids: IdFactory, count_col: str,
                        warnings: list[str]) -> list[str]:
    """Give a home to a schedule row that exists in no sizes sheet.

    ``Doors!B139`` is "Refugee", 2 doors x 4, and it appears nowhere in
    ``Flat Sizes``.  Dropping it would lose 8 doors and quietly change the total;
    inventing an area for it would be worse.  So it becomes a service entity
    with zero area, the count the workbook typed, and a warning saying exactly
    that.
    """
    from qs_engine.model import RoomCategory, RoomType, UnitType, UnitTypeRoom

    count = wb.number(sheet, f"{count_col}{row}")
    if not count:
        return []
    unit_type = UnitType(
        id=ids.make(model.project.id, "ut", name),
        project_id=model.project.id, code=name, classification="Common Area",
        is_residential=False, is_common_area=True, seq=len(model.unit_types),
        count_override=int(count),
    )
    model.unit_types.append(unit_type)
    room_type = RoomType(id=ids.make(model.project.id, "rt", name),
                         project_id=model.project.id, name=name,
                         category=RoomCategory.SERVICE)
    model.room_types.append(room_type)
    room = UnitTypeRoom(id=ids.make(unit_type.id, "room", 1, name),
                        unit_type_id=unit_type.id, room_type_id=room_type.id,
                        seq=1, label=name)
    model.unit_type_rooms.append(room)
    warnings.append(
        f"{sheet}!B{row}: {name!r} appears in the opening schedule but in no "
        f"sizes sheet. Created as a service entity with count {int(count)} and "
        f"no area -- its finishing quantities cannot be computed until it is "
        f"given dimensions."
    )
    return [room.id]


def map_openings(wb: Workbook, model: ProjectModel, ids: IdFactory) -> list[str]:
    """Type master plus both take-off schedules."""
    map_opening_types(wb, model, ids)
    warnings: list[str] = []
    # The two sheets keep the block's unit count in different columns: Doors in
    # K, Windows in Q. Neither is a formula on the common-area rows.
    for sheet, first, last, count_col in (("Doors", 4, 140, "K"),
                                          ("Windows", 3, 161, "Q")):
        _, warns = map_schedule_sheet(wb, model, ids, sheet, first, last,
                                      count_col=count_col)
        warnings.extend(warns)
    return warnings
