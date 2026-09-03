"""Infra, Amenities and Preliminary -> cost sections and lines.

Three sheets, one shape. Each is a flat Description / Unit / Quantity / Rate /
Amount list that the workbook treats as a lump sum, and between them they carry
Rs 9.66 crore that no other part of the platform has ever seen.

Nothing is auto-corrected. What changes is that the arithmetic becomes visible:

* ``Infra!E5`` (Rs 10,00,000) and ``E12`` (Rs 15,00,000) are typed amounts in a
  column where every neighbour is ``=C*D``. They import as ``1 LS x rate``, so
  the same money is there and the multiplication is on screen.
* ``Infra!C9`` is ``=K10``, and K10 is 60% of three areas summed in a corner of
  the sheet. The three areas become quantity components and the 60% becomes the
  ``hardscape_share_pct`` parameter.
* ``Infra!D9`` is ``=950*10.764`` -- a rate quoted per square foot, converted
  inside the formula. It imports as 950 under AREA_SIMPLE, so the 10.764 stays
  the project's factor rather than being baked into Rs 10,225.80.
* ``Preliminary!C3`` re-types 602.91, the boundary-wall run that ``Infra!C4``
  owns. It imports as a component referencing the same figure, with the 30 ft
  barrication height as a parameter.
"""

from __future__ import annotations

import re

from qs_engine.model import (BuildupMethod, CostLine, CostLineQty, CostSection,
                             LineStatus, ProjectModel, RateItem, RateRevision)

from ..ids import IdFactory
from ..reader import Workbook

#: ``=950*10.764`` -- a per-sq.ft rate converted in the formula.
_PER_SQFT = re.compile(r"^=\s*([0-9.]+)\s*\*\s*10\.764\s*$")


def _rate_for(wb: Workbook, model: ProjectModel, ids: IdFactory, sheet: str,
              cell: str, description: str, unit: str,
              category: str) -> str | None:
    """Give a cost line a rate item, keeping any conversion as a parameter."""
    value = wb.number(sheet, cell)
    if value is None:
        return None
    formula = (wb.formula(sheet, cell) or "").replace(" ", "")
    match = _PER_SQFT.match(formula)

    item = RateItem(
        id=ids.make(model.project.id, "rate", category, description),
        project_id=model.project.id,
        code=f"{category[:3].upper()}-{len(model.rate_items)}",
        description=description, unit=unit, category=category,
        specification=f"{sheet}!{cell}")
    revision = RateRevision(
        id=ids.make(item.id, "rev1"), rate_item_id=item.id,
        method=BuildupMethod.AREA_SIMPLE if match else BuildupMethod.CONSTANT,
        basic_rate=float(match.group(1)) if match else None,
        constant_value=None if match else float(value),
        source=f"{sheet}!{cell}" + (f" = {formula}" if formula else ""))
    model.rate_items.append(item)
    model.rate_revisions.append(revision)
    return item.id


def _section(model: ProjectModel, ids: IdFactory, code: str, name: str,
             seq: int, excel_ref: str) -> CostSection:
    section = CostSection(id=ids.make(model.project.id, "sec", code),
                          project_id=model.project.id, code=code, name=name,
                          seq=seq, excel_ref=excel_ref)
    model.cost_sections.append(section)
    return section


def map_infra(wb: Workbook, model: ProjectModel, ids: IdFactory) -> list[str]:
    """``Infra`` A2:E13 -- Rs 4.66 Cr of external development."""
    warnings: list[str] = []
    section = _section(model, ids, "external-development",
                       "External Development", 80, "Infra!E13")

    for row in range(3, 13):
        description = wb.text("Infra", f"A{row}").strip()
        if not description:
            continue
        unit = wb.text("Infra", f"B{row}").strip()
        qty = wb.number("Infra", f"C{row}")
        amount = wb.number("Infra", f"E{row}")

        line = CostLine(
            id=ids.make(section.id, f"r{row}"), project_id=model.project.id,
            section_id=section.id, seq=row, description=description,
            unit=unit or "", source_ref=f"Infra!A{row}")

        if not unit and amount is None:
            # A narrative row: "Landscape & Signages" heads the two landscape
            # lines below it and carries no money of its own.
            model.cost_lines.append(line)
            continue

        rate_id = _rate_for(wb, model, ids, "Infra", f"D{row}", description,
                            unit or "LS", "External Development")
        if rate_id is None and amount is not None:
            # A typed amount with no rate beside it -- Rs 15,00,000 of
            # miscellaneous works. Kept as one lump at its own value, so the
            # money is unchanged and the multiplication is visible.
            line.unit = "LS"
            line.qty = 1.0
            line.manual_rate = float(amount)
            line.source_ref = f"Infra!E{row}"
            warnings.append(
                f"Infra!E{row}: {description!r} is a typed amount in a column "
                f"where every neighbour is qty x rate (C-33). Imported as "
                f"1 LS x Rs {amount:,.0f}, which is the same money written so "
                f"the arithmetic shows.")
        else:
            line.qty = qty
            line.rate_item_id = rate_id

        # The hard/soft landscape split, lifted out of the side calculation.
        if description.lower().startswith(("hard scape", "soft scape")):
            share = ("hardscape_share_pct" if description.lower().startswith("hard")
                     else "softscape_share_pct")
            line.qty = None
            for label, cell in (("Ground Floor", "J7"), ("6th Podium", "J8"),
                                ("Terrace", "J9")):
                area = wb.number("Infra", cell)
                if area is None:
                    continue
                model.cost_line_qtys.append(CostLineQty(
                    id=ids.make(line.id, "q", label), cost_line_id=line.id,
                    label=label, value=float(area), factor_param_key=share))
        model.cost_lines.append(line)
    return warnings


def map_amenities(wb: Workbook, model: ProjectModel, ids: IdFactory) -> list[str]:
    """``Amenities`` A2:F29 -- Rs 3.77 Cr, grouped under seven headings."""
    section = _section(model, ids, "amenities", "Amenities", 70, "Amenities!F29")
    heading: CostLine | None = None

    for row in range(4, 29):
        marker = wb.text("Amenities", f"A{row}").strip()
        description = wb.text("Amenities", f"B{row}").strip()
        if not description:
            continue

        if marker == "#":
            heading = CostLine(
                id=ids.make(section.id, f"h{row}"), project_id=model.project.id,
                section_id=section.id, seq=row, description=description,
                source_ref=f"Amenities!B{row}")
            model.cost_lines.append(heading)
            continue

        unit = wb.text("Amenities", f"C{row}").strip()
        model.cost_lines.append(CostLine(
            id=ids.make(section.id, f"r{row}"), project_id=model.project.id,
            section_id=section.id, seq=row, description=description,
            unit=unit or "LS", qty=wb.number("Amenities", f"D{row}"),
            rate_item_id=_rate_for(wb, model, ids, "Amenities", f"E{row}",
                                   f"{heading.description if heading else ''} "
                                   f"- {description}".strip(" -"),
                                   unit or "LS", "Amenities"),
            parent_id=heading.id if heading else None,
            source_ref=f"Amenities!B{row}"))
    return []


def map_preliminary(wb: Workbook, model: ProjectModel, ids: IdFactory) -> list[str]:
    """``Preliminary`` A2:F13 -- Rs 1.23 Cr of site set-up and running costs."""
    warnings: list[str] = []
    section = _section(model, ids, "preliminaries", "Preliminaries", 10,
                       "Preliminary!F13")

    for row in range(3, 13):
        description = wb.text("Preliminary", f"B{row}").strip()
        if not description:
            continue
        unit = wb.text("Preliminary", f"D{row}").strip()
        line = CostLine(
            id=ids.make(section.id, f"r{row}"), project_id=model.project.id,
            section_id=section.id, seq=row, description=description,
            unit=unit or "LS", qty=wb.number("Preliminary", f"C{row}"),
            rate_item_id=_rate_for(wb, model, ids, "Preliminary", f"E{row}",
                                   description, unit or "LS", "Preliminaries"),
            source_ref=f"Preliminary!B{row}")

        # Barrication area is the boundary wall run x its height. The workbook
        # re-types 602.91, which Infra!C4 already owns, so changing the wall
        # moves one sheet and not the other.
        if "barric" in description.lower():
            wall = wb.number("Infra", "C4")
            if wall is not None:
                line.qty = None
                model.cost_line_qtys.append(CostLineQty(
                    id=ids.make(line.id, "q", "wall"), cost_line_id=line.id,
                    label="Boundary wall run x barrication height",
                    value=float(wall), factor=30.0 / 3.28))
                warnings.append(
                    "Preliminary!C3: the barrication area re-types 602.91, the "
                    "boundary-wall run that Infra!C4 owns. Imported as a "
                    "component of that figure, so the two cannot drift apart.")
        model.cost_lines.append(line)
    return warnings





# --------------------------------------------------------------------------
# The cost sheets -- Civil, Finishing and MEP
# --------------------------------------------------------------------------
#
# These carry quantities from sheets this platform has not modelled yet
# (Excavation, Shore Pile, Concrete & Steel, Electrical, Plumbing), so they
# import as figures with their source cell attached and ``qty_carried`` set.
# That is the CLAUDE.md import philosophy applied honestly: bring it in as it
# stands, say what it is, correct it later.
#
# The section boundaries come from the workbook's own headings in column A, not
# from the ranges the Summary sums -- which is the whole point. ``Summary!D11``
# sums I118:I125 while the MEP EXTERNAL band runs to row 126, so the Substation
# at Rs 24,00,000 sits inside the band and outside the total (C-38). Reading the
# heading puts it back where it belongs.

#: Rows that belong to a section of their own rather than the band above them.
#: ``None`` means the row is already held elsewhere and must not be imported
#: twice -- ``Cost Sheet Tower!I127`` is ``=Infra!E13``, and the External
#: Development section carries those ten Infra lines in full.
_OWN_SECTION: dict[str, tuple[str | None, str, int, str]] = {
    "External Development Civil": (None, "", 0, "already held as Infra"),
    "Post Construction": ("post-construction", "Post Construction", 90, ""),
}

#: Where each cost sheet's bands begin, and what the Summary calls them.
_TOWER_BANDS = (
    ("SHELL AND CORE", "civil", "Civil", 20),
    ("FINISHING", "finishing", "Finishing", 30),
    ("MEP", "mep", "MEP", 40),
    ("MEP NTA", "mep-nta", "MEP NTA", 50),
    ("MEP EXTERNAL", "mep-external", "MEP External", 60),
)


def map_cost_sheet(wb: Workbook, model: ProjectModel, ids: IdFactory, *,
                   sheet: str = "Cost Sheet Tower", first_row: int = 5,
                   last_row: int = 128,
                   opens_with: tuple[str, str, int] | None = None) -> list[str]:
    """One detailed cost sheet into sections and carried lines.

    ``opens_with`` names the band a sheet starts in when its first rows sit
    above any heading -- ``Cost Sheet office`` begins with seven rows of
    plaster before its first ``A`` marker, and the Summary counts them as Civil.
    """
    warnings: list[str] = []
    bands = {name: (code, label, seq) for name, code, label, seq in _TOWER_BANDS}
    sections: dict[str, CostSection] = {}
    current: CostSection | None = None

    def band(code: str, label: str, seq: int) -> CostSection:
        key = f"{code}-{sheet}"
        if key not in sections:
            sections[key] = _section(model, ids, key, label, seq,
                                     f"{sheet}, band {label!r}")
        return sections[key]

    if opens_with:
        current = band(*opens_with)

    for row in range(first_row, last_row + 1):
        heading = wb.text(sheet, f"A{row}").strip()
        description = wb.text(sheet, f"B{row}").strip()
        if heading and heading.upper() in bands:
            current = band(*bands[heading.upper()])
        if not description or current is None:
            continue

        # Two rows at the foot of the tower sheet belong to sections of their
        # own, not to the MEP band they happen to sit under. I127 is
        # ``=Infra!E13``, which the External Development section already holds
        # in full; importing it here as well would count Rs 4.66 crore twice.
        if description in _OWN_SECTION:
            code, label, seq, note = _OWN_SECTION[description]
            if code is None:
                continue
            current = band(code, label, seq)

        amount = wb.number(sheet, f"I{row}")
        if amount is None:
            continue
        qty = wb.number(sheet, f"G{row}")
        unit = wb.text(sheet, f"F{row}").strip() or "LS"
        rate = wb.number(sheet, f"H{row}")

        # On 29 rows the "Rate" column is a per-sq.ft indicator against a
        # quantity of 1, so G x H is unrelated to the amount it sits beside
        # (C-43). Where they disagree the amount is the datum and the line
        # imports as one lump, with the disagreement recorded.
        derived_ok = (qty not in (None, 0) and rate is not None
                      and abs(qty * rate - amount) <= max(1.0, abs(amount) * 1e-6))
        if derived_ok:
            line_qty, line_rate, line_unit = qty, rate, unit
        else:
            line_qty, line_rate, line_unit = 1.0, float(amount), "LS"
            if qty not in (None, 0) and rate:
                warnings.append(
                    f"{sheet}!I{row}: {description!r} shows quantity {qty:g} "
                    f"{unit} at {rate:,.2f}, which multiplies to "
                    f"{qty * rate:,.2f}, not the {amount:,.2f} in the amount "
                    f"column (C-43). The amount is taken as the figure.")

        model.cost_lines.append(CostLine(
            id=ids.make(current.id, f"r{row}"), project_id=model.project.id,
            section_id=current.id, seq=row, description=description,
            unit=line_unit, qty=line_qty, manual_rate=line_rate,
            source_ref=f"{sheet}!I{row}", qty_carried=True))
    return warnings


def map_cost_lines(wb: Workbook, model: ProjectModel, ids: IdFactory) -> list[str]:
    """Every cost sheet the platform reads, in the order a QS reads them."""
    warnings = list(map_preliminary(wb, model, ids))
    warnings += map_cost_sheet(wb, model, ids)
    warnings += map_cost_sheet(wb, model, ids, sheet="Cost Sheet office",
                               first_row=5, last_row=48,
                               opens_with=("civil", "Civil", 20))
    warnings += map_amenities(wb, model, ids)
    warnings += map_infra(wb, model, ids)
    return warnings
