"""Room Conf -> floors, unit types and the floor/unit-type mix.

The sheet is a 37-row x 28-column occupancy matrix: floors down the side, unit
types across the top, a count in each cell.  Three things come out of it, and
one thing deliberately does not.

**Classification is parsed, then becomes an attribute.**  The workbook derives
its BHK split from hand-typed column lists::

    L43 = L40+N40+T40                                    1BHK -> 28
    L44 = M40+O40+R40+U40+V40+Y40+Z40+P40                2BHK -> 143
    L45 = Q40+S40+W40+X40                                3BHK -> 107

``P40`` sits at the end of the 2BHK list rather than in sequence -- the visible
scar of a unit type added after the formula was written.  Add another and the
split silently stops adding up (C-21).  Here the classification is read off the
column header once, stored on the unit type, and every split is a group-by.

**What does not come across:** ``C40 = SUM(C3:C39)`` = 121.40, labelled "Total
Apartments".  It is the sum of the floor-to-floor heights -- the building's
height in metres, wearing the label of a count.  Both numbers are produced
here, each under its own name.
"""

from __future__ import annotations

import re

from qs_engine.model import (Building, Floor, FloorType, FloorUnitMix, Project,
                             ProjectModel, UnitType)

from ..ids import IdFactory
from ..reader import Workbook

SHEET = "Room Conf"
HEADER_ROW = 2
FIRST_FLOOR_ROW = 3
LAST_FLOOR_ROW = 39

#: Column headers that are structure, not unit types.
_NON_UNIT_HEADERS = {"sr no", "floor no", "flr to flr ht"}

_FLOOR_TYPE_PATTERNS: tuple[tuple[str, FloorType], ...] = (
    ("basement", FloorType.BASEMENT),
    ("ground", FloorType.GROUND),
    ("podium", FloorType.PODIUM),
    ("refuge", FloorType.REFUGE),
    ("terrace", FloorType.TERRACE),
    ("lmr", FloorType.LMR),
    ("machine", FloorType.LMR),
)


def classify(header: str) -> tuple[str, bool, bool]:
    """(classification, is_residential, is_common_area) from a column header.

    ``"Flat 1B,\\n2BHK"`` -> ``("2BHK", True, False)``
    ``"Flat 1A"``         -> ``("1BHK", True, False)``  -- no suffix means 1BHK,
                              which the workbook confirms: L43 sums exactly the
                              three unsuffixed flat columns to 28.
    ``"Office 3"``        -> ``("Office", False, False)``
    ``"Common Lobby 1"``  -> ``("Common Area", False, True)``
    """
    text = " ".join(str(header).split())
    bhk = re.search(r"(\d+)\s*BHK", text, re.IGNORECASE)
    if bhk:
        return f"{bhk.group(1)}BHK", True, False
    lowered = text.lower()
    if lowered.startswith("office"):
        return "Office", False, False
    if lowered.startswith("shop") or lowered.startswith("retail"):
        return "Retail", False, False
    if lowered.startswith("flat") or lowered.startswith("apartment"):
        return "1BHK", True, False
    return "Common Area", False, True


def floor_type_of(name: str) -> FloorType:
    lowered = name.lower()
    for needle, ftype in _FLOOR_TYPE_PATTERNS:
        if needle in lowered:
            return ftype
    return FloorType.TYPICAL


def _column_letters(wb: Workbook, sheet: str, row: int) -> list[str]:
    cells = wb.sheet(sheet)
    refs = [c for c in cells.values() if c.row == row and c.as_text()]
    return [c.ref[:-len(str(row))] for c in sorted(refs, key=lambda c: c.col)]


def map_room_conf(wb: Workbook, model: ProjectModel, ids: IdFactory) -> ProjectModel:
    """Populate floors, unit types and the floor/unit-type mix."""
    project_id = model.project.id
    building = Building(id=ids.make(project_id, "tower"), project_id=project_id,
                        name="Tower", building_type="tower")
    model.buildings.append(building)

    # -- unit type columns, read off the header row ------------------------
    columns: dict[str, UnitType] = {}
    for letter in _column_letters(wb, SHEET, HEADER_ROW):
        header = wb.text(SHEET, f"{letter}{HEADER_ROW}")
        if " ".join(header.split()).lower() in _NON_UNIT_HEADERS:
            continue
        classification, residential, common = classify(header)
        code = " ".join(header.split()).replace(f", {classification}", "")
        unit_type = UnitType(
            id=ids.make(project_id, "ut", header),
            project_id=project_id,
            code=code,
            classification=classification,
            is_residential=residential,
            is_common_area=common,
            seq=len(columns),
        )
        columns[letter] = unit_type
        model.unit_types.append(unit_type)

    # -- floors, and the mix on each ---------------------------------------
    for row in range(FIRST_FLOOR_ROW, LAST_FLOOR_ROW + 1):
        name = wb.text(SHEET, f"B{row}")
        if not name:
            continue
        seq = int(wb.number(SHEET, f"A{row}", row - FIRST_FLOOR_ROW + 1) or 0)
        floor = Floor(
            id=ids.make(project_id, "floor", seq, name),
            building_id=building.id,
            seq=seq,
            name=name,
            floor_to_floor_ht=float(wb.number(SHEET, f"C{row}", 0.0) or 0.0),
            floor_type=floor_type_of(name),
        )
        model.floors.append(floor)

        for letter, unit_type in columns.items():
            count = wb.number(SHEET, f"{letter}{row}")
            if not count:
                continue
            model.floor_unit_mix.append(FloorUnitMix(
                id=ids.make(floor.id, unit_type.id),
                floor_id=floor.id,
                unit_type_id=unit_type.id,
                count=int(count),
            ))
    return model


def new_model(code: str = "AVS", name: str = "AVS Rudraksh",
              city: str = "Mulund") -> ProjectModel:
    return ProjectModel(project=Project(id="avs", code=code, name=name, city=city))
