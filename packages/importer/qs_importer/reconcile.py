"""Reconciliation: the platform's numbers against the workbook's, side by side.

The acceptance gate.  Every line is PASS (identical to the paisa), EXPLAINED (a
difference of exactly the size a named defect predicts), or FAIL (anything
else).  A FAIL blocks acceptance.

You chose to compute corrected numbers rather than mirror the workbook's
defects, which removes the easy test -- "every difference is zero".  The
replacement is the expected-delta ledger below: each correction carries a
*precomputed exact* difference, so a bug cannot hide inside one.  An explained
difference of the wrong size fails just as loudly as an unexplained one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from qs_engine.model import OpeningKind
from qs_engine.rules.schedule import (opening_schedule, opening_totals,
                                      total_openings)
from qs_engine.rules.unit_area import unit_type_total_sqft

from .pipeline import ImportResult

TOLERANCE = 0.01


class Status(Enum):
    PASS = "PASS"
    EXPLAINED = "EXPLAINED"
    FAIL = "FAIL"


@dataclass
class Line:
    section: str
    label: str
    excel: float
    platform: float
    excel_ref: str = ""
    expected_delta: float | None = None
    explanation: str = ""

    @property
    def difference(self) -> float:
        return self.platform - self.excel

    @property
    def status(self) -> Status:
        if abs(self.difference) <= TOLERANCE:
            return Status.PASS
        if self.expected_delta is not None and \
                abs(self.difference - self.expected_delta) <= TOLERANCE:
            return Status.EXPLAINED
        return Status.FAIL


def build_lines(result: ImportResult) -> list[Line]:
    model, params, wb = result.model, result.params, result.workbook
    lines: list[Line] = []

    def by_code(code: str):
        return next(u for u in model.unit_types if u.code == code)

    # -- Module 1 ---------------------------------------------------------
    lines.append(Line("Room Config", "Floors", 37, len(model.floors), "Room Conf!A3:A39"))
    lines.append(Line("Room Config", "Total flats",
                      wb.number("Room Conf", "L41") or 0,
                      sum(model.unit_count(u.id) for u in model.unit_types
                          if u.code.startswith("Flat")), "Room Conf!L41"))
    lines.append(Line("Room Config", "Total offices",
                      wb.number("Room Conf", "D41") or 0,
                      sum(model.unit_count(u.id) for u in model.unit_types
                          if u.classification == "Office"), "Room Conf!D41"))
    split = model.counts_by_classification()
    for bhk, ref in (("1BHK", "L43"), ("2BHK", "L44"), ("3BHK", "L45")):
        lines.append(Line("Room Config", f"{bhk} units",
                          wb.number("Room Conf", ref) or 0, split.get(bhk, 0),
                          f"Room Conf!{ref}"))
    lines.append(Line("Room Config", "Building height (m)",
                      wb.number("Room Conf", "C40") or 0,
                      sum(f.floor_to_floor_ht for f in model.floors),
                      "Room Conf!C40 -- labelled 'Total Apartments'"))

    # -- Module 2 ---------------------------------------------------------
    type_rows = {
        "Flat 1A": "I4", "Flat 1B": "I11", "Flat 2A": "I21", "Flat 2B": "I28",
        "Flat 3A": "I38", "Flat 3B": "I48", "Flat 4A": "I60", "Flat 4B": "I70",
        "Flat 5A": "I82", "Flat 5B": "I89", "Flat 6": "I99", "Flat 7": "I109",
        "Flat 8": "I121", "Flat 9": "I133", "Flat 10": "I143",
    }
    for code, ref in type_rows.items():
        excel = wb.number("Flat Sizes", ref) or 0.0
        platform = unit_type_total_sqft(by_code(code).id, model, params).value
        line = Line("Unit Sizes", f"{code} total (sq.ft)", excel, platform,
                    f"Flat Sizes!{ref}")
        if code == "Flat 3B":
            line.expected_delta = 23.1292 * 27
            line.explanation = (
                "C-3: Flat Sizes!E57 holds the hardcoded 7.01 where D57*10.764 "
                "gives 30.14. 7.01 is the perimeter from G57, pasted one column "
                "left. +23.13 sq.ft across 27 units.")
        lines.append(line)

    # -- Module 3 ---------------------------------------------------------
    doors = {l.code.upper(): l for l in opening_schedule(model, (OpeningKind.DOOR,))}
    for row in range(146, 150):
        code = wb.text("Doors", f"D{row}").strip().upper()
        excel = wb.number("Doors", f"F{row}") or 0.0
        line = Line("Openings", f"Door {code} (nos)", excel,
                    doors[code].count if code in doors else 0.0,
                    f"Doors!F{row}")
        if code == "FRD":
            line.expected_delta = -2
            line.explanation = (
                "C-36: the two smoke-check lobbies are 36 in Flat Sizes!H156/H157 "
                "and 37 in Doors!K137/K138. Both typed, neither a formula. One "
                "count per entity here, so the schedule is 2 lower.")
        lines.append(line)

    total = total_openings(model, (OpeningKind.DOOR,)).value
    lines.append(Line("Openings", "Total doors", wb.number("Doors", "L141") or 0.0,
                      total, "Doors!L141", expected_delta=-2,
                      explanation="C-36, as above. Doors!E141 separately reports "
                                  "58 by summing E67:E140 while its neighbours "
                                  "sum from row 5 (C-12)."))

    windows = {l.code.upper(): l for l in
               opening_schedule(model, (OpeningKind.WINDOW, OpeningKind.VENTILATOR,
                                        OpeningKind.RAILING))}
    for row in range(166, 178):
        code = wb.text("Windows", f"D{row}").strip().upper()
        if not code:
            continue
        excel = wb.number("Windows", f"F{row}") or 0.0
        line = windows.get(code)
        unit = line.unit if line else "SQM"
        lines.append(Line("Openings", f"{code} ({'RM' if unit == 'RM' else 'sq.m'})",
                          excel, line.quantity if line else 0.0, f"Windows!F{row}"))

    # -- Opening costs ----------------------------------------------------
    # The counts were always reconciled; the money is new. `D&W Schedule`
    # column F carries a rate against every type and nothing was reading it.
    bands = {t.key: t for t in opening_totals(model, params)}

    doors_line = Line("Opening Costs", "Doors: total cost",
                      wb.number("Doors", "H150") or 0.0,
                      bands["doors"].amount if "doors" in bands else 0.0,
                      "Doors!H150 = SUM(H146:H149)")
    doors_line.expected_delta = -60000.0
    doors_line.explanation = (
        "C-36 again, in money: the two smoke-check lobbies are 36 here and 37 "
        "in Doors!K137/K138, so the schedule carries 2 fewer FRD at Rs 30,000 "
        "each. The other three door types agree to the rupee.")
    lines.append(doors_line)

    # Windows!D166:H177 lists windows, the ventilator and both railings in one
    # table, so it is compared against the same three bands added together.
    glazing = sum(bands[k].amount for k in ("windows", "ventilators", "railings")
                  if k in bands)
    lines.append(Line("Opening Costs", "Windows, ventilators & railings",
                      wb.number("Windows", "H178") or 0.0, glazing,
                      "Windows!H178 = SUM(H166:H177)"))

    curtain = Line("Opening Costs", "Curtain wall",
                   wb.number("D&W Schedule", "G33") or 0.0,
                   bands["curtain_wall"].amount if "curtain_wall" in bands else 0.0,
                   "D&W Schedule!G33 = E33*F33")
    curtain.expected_delta = -(wb.number("D&W Schedule", "G33") or 0.0)
    curtain.explanation = (
        "Q-1, open: the eight bays are priced but reach no room, because the "
        "workbook multiplies them by 32 (D&W Schedule!E32) where the building "
        "has 4 office floors. Rather than guess, the bays carry their rate and "
        "report as measured-at-nothing until the count is settled.")
    lines.append(curtain)

    # -- Cost lines and the project roll-up --------------------------------
    from qs_engine.rules.cost_lines import compute_cost_lines, section_total
    from qs_engine.rules.summary import project_summary

    cost_lines = compute_cost_lines(model, params)
    by_code = {s.code: s for s in model.cost_sections}
    for code, ref, label in (("preliminaries", "Preliminary!F13", "Preliminaries"),
                             ("amenities", "Amenities!F29", "Amenities"),
                             ("external-development", "Infra!E13",
                              "External Development (Infra)")):
        section = by_code.get(code)
        if section is None:
            continue
        sheet, cell = ref.split("!")
        lines.append(Line("Cost Lines", label, wb.number(sheet, cell) or 0.0,
                          section_total(cost_lines, section.id), ref))

    area = wb.number("Construction Area", "S45") or 0.0
    summary = project_summary(model, params, area)

    #: The Substation, recovered. `Summary!D11` sums I118:I125 while the MEP
    #: EXTERNAL band runs to row 126, so Rs 24,00,000 is computed, formatted and
    #: totalled into the cost sheet's own I129 while reaching the project budget
    #: through nothing. Sections here are filters, so it comes back -- and every
    #: uplift above it moves by exactly the compounded amount.
    substation = 2_400_000.0
    uplift = 1 + params["escalation_pct"] + params["contingency_pct"]
    explanation = (
        "C-38: Cost Sheet Tower!I126 is the Substation at Rs 24,00,000. It sits "
        "under the MEP EXTERNAL heading, which runs to row 126, but Summary!D11 "
        "sums I118:I125 and stops one row short -- so the workbook computes it, "
        "totals it into its own I129, and never carries it into the budget. "
        "Nothing in the workbook compares I129 with the Summary. Sections here "
        "are filters over the lines that name them, so it is counted.")

    for label, cell, platform, delta in (
            ("Section subtotal", "D15", summary.subtotal, substation),
            ("Before tax (+esc, +cont)", "D18", summary.before_tax,
             substation * uplift),
            ("Project total (with GST)", "D20", summary.total,
             substation * uplift * (1 + params["gst_pct"]))):
        excel = (wb.number("Summary", cell) or 0.0) * 1e7   # the sheet is in crore
        lines.append(Line("Project Summary", label, excel, platform,
                          f"Summary!{cell}", expected_delta=delta,
                          explanation=explanation))

    # -- The kitchen counters ---------------------------------------------
    #
    # A kitchen is measured off its counters, not its perimeter, and until now
    # the platform measured neither: the four counter rows sat at zero while
    # the workbook priced them at Rs 1.31 crore.  Three of the four now
    # reproduce the workbook to the paisa.  The fourth does not, and the reason
    # is stated here rather than absorbed into a tolerance.
    from qs_engine.rules.takeoff import compute_takeoff

    takeoff = compute_takeoff(model, params)

    def priced(**match) -> float:
        return sum(l.total_amount for l in takeoff if l.is_priced
                   and all(getattr(l, k) == v for k, v in match.items()))

    def book(*refs: str) -> float:
        return sum(wb.number(*ref.split("!")) or 0.0 for ref in refs)

    #: The three office Pantries whose carpet area and perimeter match no
    #: take-off block.  The workbook has one Pantry block and applies it to all
    #: 32 office units; three of the eight pantries are a different size, so
    #: here they import unmeasured and are reported, rather than borrowing a
    #: block that measures a different room (C-11).  12 units x 1.5 m of
    #: counter, and 12 x 3.6 sq m of dado above it, at the workbook's own rates.
    unmeasured_run_m = 18.0
    unmeasured_dado_sqm = 43.2
    office_counter_rate = (book("Internal Finishes Offices!F87")
                           / (wb.number("Internal Finishes Offices", "D87") or 1.0))
    office_dado_rate = (book("Internal Finishes Offices!F84")
                        / (wb.number("Internal Finishes Offices", "D84") or 1.0))
    pantry_note = (
        "Three of the eight office Pantries are a different size from the one "
        "Pantry block on Internal Finishes Offices, which the workbook applies "
        "to all 32 office units regardless. They import unmeasured and are "
        "reported as such, rather than taking their counters from a block that "
        "measures a different room.")

    lines.append(Line(
        "Kitchen counters", "Main platform",
        book("Internal Finishes Flats!F2013"),
        priced(finish_name="Kitchen Platform"),
        "Internal Finishes Flats!F2013 = SUMIF(R,I2013,P)"))
    lines.append(Line(
        "Kitchen counters", "Service platform",
        book("Internal Finishes Flats!F2014", "Internal Finishes Offices!F87"),
        priced(finish_name="Service Platform"),
        "Internal Finishes Flats!F2014 + Internal Finishes Offices!F87",
        expected_delta=-unmeasured_run_m * office_counter_rate,
        explanation=pantry_note))
    lines.append(Line(
        "Kitchen counters", "Dado above the counter",
        book("Internal Finishes Flats!F2011", "Internal Finishes Offices!F84"),
        priced(qty_rule="dado_above_platform"),
        "Internal Finishes Flats!F2011 + Internal Finishes Offices!F84",
        expected_delta=-unmeasured_dado_sqm * office_dado_rate,
        explanation=pantry_note))
    lines.append(Line(
        "Kitchen counters", "Dado below the counter",
        book("Internal Finishes Flats!F2012"),
        priced(finish_name="Dado Below Kitchen Platform"),
        "Internal Finishes Flats!F2012 = SUMIF(R,I2012,P)"))

    # -- Module 4 ---------------------------------------------------------
    from qs_engine.model import BuildupMethod, RateRevision
    from qs_engine.rules.rate_buildup import build_rate

    from .mappers.rates import classify_formula
    for sheet, last in (("Rate List - Flats", 300), ("Rate List - Office", 400)):
        checked = failed = 0
        for row in range(4, last + 1):
            value = wb.number(sheet, f"G{row}")
            formula = wb.formula(sheet, f"G{row}")
            if value is None or not formula:
                continue
            method, wastage, factor, constant, frame_w = classify_formula(formula, value)
            if method is BuildupMethod.LINK:
                continue
            revision = RateRevision(
                id="x", rate_item_id="y", method=method,
                basic_rate=wb.number(sheet, f"E{row}"),
                laying_rate=wb.number(sheet, f"F{row}"), wastage_pct=wastage,
                adjustment_factor=factor, adjustment_constant=constant,
                frame_width_m=frame_w,
                constant_value=value if method is BuildupMethod.CONSTANT else None)
            checked += 1
            if abs(build_rate(revision, params).value - value) > TOLERANCE:
                failed += 1
        lines.append(Line("Rate Library", f"{sheet}: rows reproduced",
                          checked, checked - failed, f"{sheet}!G4:G{last}"))
    return lines


def render(result: ImportResult) -> str:
    from qs_engine.validation import Severity, validate

    lines = build_lines(result)
    out: list[str] = []
    push = out.append

    sheets, populated, formulas = result.workbook.totals()
    push("=" * 96)
    push(f"  RECONCILIATION -- {result.model.project.name}")
    push(f"  Excel: {result.workbook.path.name}")
    push("=" * 96)
    push("")
    push(f"  Staged: {sheets} sheets, {populated:,} populated cells, "
         f"{formulas:,} formulas")
    counts = ", ".join(f"{k} {v}" for k, v in result.counts.items())
    push(f"  Mapped: {counts}")
    push("")

    section = None
    for line in lines:
        if line.section != section:
            section = line.section
            push("-" * 96)
            push(f"  {section.upper()}")
            push("-" * 96)
            push(f"  {'':38}{'Excel':>16}{'Platform':>16}{'Difference':>14}  Status")
        mark = {"PASS": "PASS", "EXPLAINED": "EXPL", "FAIL": "FAIL"}[line.status.value]
        push(f"  {line.label:38}{line.excel:16,.2f}{line.platform:16,.2f}"
             f"{line.difference:14,.2f}  {mark}")
        if line.status is Status.EXPLAINED:
            for chunk in _wrap(line.explanation, 86):
                push(f"      {chunk}")

    passed = sum(1 for l in lines if l.status is Status.PASS)
    explained = sum(1 for l in lines if l.status is Status.EXPLAINED)
    failed = [l for l in lines if l.status is Status.FAIL]
    push("")
    push("=" * 96)
    push(f"  {passed} PASS   {explained} EXPLAINED   {len(failed)} FAIL"
         f"      -- acceptance {'GRANTED' if not failed else 'BLOCKED'}")
    push("=" * 96)
    for line in failed:
        push(f"  FAIL  {line.section} / {line.label}: excel {line.excel:,.4f} "
             f"vs platform {line.platform:,.4f}  ({line.excel_ref})")

    report = validate(result.model, result.params)
    push("")
    push("-" * 96)
    push(f"  VALIDATION -- {report.summary()}    health {report.health_score():.0f}/100"
         f"    can issue: {'yes' if report.can_issue else 'no'}")
    push("-" * 96)
    for severity in (Severity.BLOCKING, Severity.WARNING):
        for finding in report.of(severity)[:8]:
            push(f"  {finding}")
        extra = len(report.of(severity)) - 8
        if extra > 0:
            push(f"        ... and {extra} more {severity.value}")

    if result.warnings:
        push("")
        push("-" * 96)
        push(f"  IMPORT NOTES ({len(result.warnings)})")
        push("-" * 96)
        for warning in result.warnings[:10]:
            for i, chunk in enumerate(_wrap(warning, 90)):
                push(("  ! " if i == 0 else "    ") + chunk)
        if len(result.warnings) > 10:
            push(f"  ... and {len(result.warnings) - 10} more")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
