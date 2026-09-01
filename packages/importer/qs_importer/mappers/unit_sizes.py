"""Flat Sizes / Office Sizes -> room types and per-unit-type room lists.

The sheet is a stack of blocks, one per unit type::

    r11  Flat 1B,2BHK      H11 = 'Room Conf'!M40 = 18      I11 = +H11*F20
    r12    Living, Dining   D 25.47   E =D12*10.764   F =E12*C12   G 22.71
    ...
    r19    Balcony          D  2.60   ...
    r20  Sub Total          D =SUM(D12:D19)  F =SUM(F12:F19) = 757.355

Blocks are found by structure, not by hard-coded row numbers, because block
length is exactly what varies: AVS's fifteen flat types run from five rooms
(Flat 1A) to ten (Flat 4B, Flat 7, Flat 8).  A flat with four bathrooms is four
rows.  Nothing here counts rooms or assumes a maximum.

**Column E is not imported.**  It is ``=D*10.764`` -- a derived value, and the
engine derives it.  That is not tidiness: ``E57`` in this sheet is the hardcoded
number 7.01 where the formula would give ``2.80 x 10.764 = 30.14``.  7.01 is the
*perimeter* from column G, pasted one column left.  It understates Flat 3B's
balcony by 23.13 sq.ft across 27 units, and it survived because the result
looked plausible (C-3).  Import the input, derive the rest, and there is no cell
to paste into.
"""

from __future__ import annotations

import re

from qs_engine.model import (ProjectModel, RoomCategory, RoomType, UnitType,
                             UnitTypeRoom)

from ..ids import IdFactory
from ..reader import Workbook

SHEET_FLATS = "Flat Sizes"
COMMON_FIRST_ROW, COMMON_LAST_ROW = 154, 161
SHEET_OFFICES = "Office Sizes"

COL_LABEL, COL_COUNT, COL_AREA_SQM = "B", "C", "D"
COL_TOTAL, COL_PERIMETER, COL_NOS = "F", "G", "H"

_SUBTOTAL_MARKERS = {"sub total", "subtotal", "total"}

#: Room name -> category.  Ordered: the first match wins, so "Smoke Check
#: Lobby" is circulation before "check" can mean anything else.
_CATEGORY_PATTERNS: tuple[tuple[str, RoomCategory], ...] = (
    ("toilet", RoomCategory.TOILET),
    ("bath", RoomCategory.TOILET),
    ("powder", RoomCategory.TOILET),
    ("w.c", RoomCategory.TOILET),
    ("kitchen", RoomCategory.KITCHEN),
    ("utility", RoomCategory.UTILITY),
    ("balcony", RoomCategory.BALCONY),
    ("deck", RoomCategory.BALCONY),
    ("terrace", RoomCategory.BALCONY),
    ("lobby", RoomCategory.CIRCULATION),
    ("passage", RoomCategory.CIRCULATION),
    ("corridor", RoomCategory.CIRCULATION),
    ("foyer", RoomCategory.CIRCULATION),
    ("staircase", RoomCategory.CIRCULATION),
    ("stair", RoomCategory.CIRCULATION),
    ("entrance", RoomCategory.CIRCULATION),
    ("duct", RoomCategory.SERVICE),
    ("shaft", RoomCategory.SERVICE),
    ("lift", RoomCategory.SERVICE),
    ("electric", RoomCategory.SERVICE),
    ("fire", RoomCategory.SERVICE),
    ("meter", RoomCategory.SERVICE),
    ("refuge", RoomCategory.SERVICE),
    ("bedroom", RoomCategory.HABITABLE),
    ("living", RoomCategory.HABITABLE),
    ("dining", RoomCategory.HABITABLE),
    ("study", RoomCategory.HABITABLE),
    ("multi purpose", RoomCategory.HABITABLE),
    ("multipurpose", RoomCategory.HABITABLE),
)


def categorise(room_name: str) -> RoomCategory:
    """Best-guess category for a room name.

    A guess, and treated as one: the category is editable in the UI, because
    getting it wrong changes which finishes apply.
    """
    lowered = " ".join(str(room_name).split()).lower()
    for needle, category in _CATEGORY_PATTERNS:
        if needle in lowered:
            return category
    return RoomCategory.HABITABLE


def normalise_type_name(raw: str) -> str:
    """``"Flat 1B,\\n2BHK"`` -> ``"Flat 1B"``.

    Strips the classification suffix so the same type matches between
    ``Room Conf``'s header row and this sheet's block headers.
    """
    text = " ".join(str(raw).split())
    return re.sub(r",?\s*\d+\s*BHK\s*$", "", text, flags=re.IGNORECASE).strip(" ,")


def _is_subtotal(label: str) -> bool:
    return " ".join(str(label).split()).lower() in _SUBTOTAL_MARKERS


def _unit_type_index(model: ProjectModel) -> dict[str, UnitType]:
    return {normalise_type_name(ut.code).lower(): ut for ut in model.unit_types}


def _room_type_for(name: str, model: ProjectModel, ids: IdFactory,
                   cache: dict[str, RoomType]) -> RoomType:
    """Room types are open master data -- unseen names create new ones."""
    key = " ".join(str(name).split()).lower()
    if key in cache:
        return cache[key]
    room_type = RoomType(
        id=ids.make(model.project.id, "rt", name),
        project_id=model.project.id,
        name=" ".join(str(name).split()),
        category=categorise(name),
    )
    model.room_types.append(room_type)
    cache[key] = room_type
    return room_type


def _find_blocks(wb: Workbook, sheet: str, first_row: int,
                 last_row: int) -> list[tuple[int, int]]:
    """Locate (header_row, subtotal_row) pairs by structure.

    A header row carries a unit count in column H; the block ends at the next
    Sub Total.  Block length is never assumed.
    """
    blocks: list[tuple[int, int]] = []
    header: int | None = None
    for row in range(first_row, last_row + 1):
        label = wb.text(sheet, f"{COL_LABEL}{row}")
        if not label:
            continue
        if _is_subtotal(label):
            if header is not None:
                blocks.append((header, row))
                header = None
            continue
        if wb.number(sheet, f"{COL_NOS}{row}") is not None:
            header = row
    return blocks


def map_unit_sizes(wb: Workbook, model: ProjectModel, ids: IdFactory,
                   sheet: str = SHEET_FLATS, first_row: int = 4,
                   last_row: int = 152) -> ProjectModel:
    """Read one sizes sheet into ``unit_type_room`` rows."""
    by_name = _unit_type_index(model)
    room_type_cache: dict[str, RoomType] = {
        rt.name.lower(): rt for rt in model.room_types
    }

    for header_row, subtotal_row in _find_blocks(wb, sheet, first_row, last_row):
        raw_name = wb.text(sheet, f"{COL_LABEL}{header_row}")
        key = normalise_type_name(raw_name).lower()
        unit_type = by_name.get(key)
        if unit_type is None:
            # A type present in the sizes sheet but absent from the floor
            # matrix. Kept, with a zero count, rather than dropped -- an
            # orphan that is visible is fixable.
            unit_type = UnitType(
                id=ids.make(model.project.id, "ut", raw_name),
                project_id=model.project.id,
                code=normalise_type_name(raw_name),
                classification="Unassigned",
                seq=len(model.unit_types),
            )
            model.unit_types.append(unit_type)
            by_name[key] = unit_type

        seq = 0
        for row in range(header_row + 1, subtotal_row):
            label = wb.text(sheet, f"{COL_LABEL}{row}")
            area = wb.number(sheet, f"{COL_AREA_SQM}{row}")
            if not label or area is None:
                continue
            seq += 1
            room_type = _room_type_for(label, model, ids, room_type_cache)
            model.unit_type_rooms.append(UnitTypeRoom(
                id=ids.make(unit_type.id, "room", seq, label),
                unit_type_id=unit_type.id,
                room_type_id=room_type.id,
                seq=seq,
                label=" ".join(label.split()),
                count_per_unit=float(wb.number(sheet, f"{COL_COUNT}{row}", 1.0) or 1.0),
                carpet_area_sqm=float(area),
                perimeter_m=float(wb.number(sheet, f"{COL_PERIMETER}{row}", 0.0) or 0.0),
            ))
    return model


def map_common_areas(wb: Workbook, model: ProjectModel, ids: IdFactory,
                     sheet: str = SHEET_FLATS,
                     first_row: int = COMMON_FIRST_ROW,
                     last_row: int = COMMON_LAST_ROW) -> ProjectModel:
    """The common-area block, where each row is its own single-room entity.

    These rows do not follow the header/Sub Total shape of the flat blocks --
    lobbies, lifts, ducts and staircases each stand alone with their own count
    in column H.  Two workbook defects live here and neither is carried across:

    * ``I154:I161 = C*F*H`` while ``I4:I143 = H*F``.  Since ``F`` already equals
      ``E*C``, the common-area rows multiply by the room count twice (C-28).
      Every row is derived the same way here, so it cannot recur.
    * ``H155`` reads ``'Room Conf'!AA40`` on the *Common Lobby 2* row, where it
      should read ``AB40`` (C-29).  Both are 37 today, so nothing looks wrong.
      Counts here come from a relationship or an explicit override, not from a
      typed cell reference that can point one column left.
    """
    by_name = _unit_type_index(model)
    room_type_cache: dict[str, RoomType] = {
        rt.name.lower(): rt for rt in model.room_types
    }
    for row in range(first_row, last_row + 1):
        label = wb.text(sheet, f"{COL_LABEL}{row}")
        area = wb.number(sheet, f"{COL_AREA_SQM}{row}")
        if not label or area is None or _is_subtotal(label):
            continue
        name = " ".join(label.split())
        unit_type = by_name.get(normalise_type_name(name).lower())
        if unit_type is None:
            unit_type = UnitType(
                id=ids.make(model.project.id, "ut", name),
                project_id=model.project.id,
                code=name,
                classification="Common Area",
                is_residential=False,
                is_common_area=True,
                seq=len(model.unit_types),
            )
            model.unit_types.append(unit_type)
            by_name[normalise_type_name(name).lower()] = unit_type
        # Only override when the floor matrix does not already carry this type.
        if not any(m.unit_type_id == unit_type.id for m in model.floor_unit_mix):
            nos = wb.number(sheet, f"{COL_NOS}{row}")
            if nos:
                unit_type.count_override = int(nos)
        room_type = _room_type_for(name, model, ids, room_type_cache)
        model.unit_type_rooms.append(UnitTypeRoom(
            id=ids.make(unit_type.id, "room", 1, name),
            unit_type_id=unit_type.id,
            room_type_id=room_type.id,
            seq=1,
            label=name,
            count_per_unit=float(wb.number(sheet, f"{COL_COUNT}{row}", 1.0) or 1.0),
            carpet_area_sqm=float(area),
            perimeter_m=float(wb.number(sheet, f"{COL_PERIMETER}{row}", 0.0) or 0.0),
        ))
    return model
