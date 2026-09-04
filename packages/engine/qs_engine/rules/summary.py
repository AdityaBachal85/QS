"""The project roll-up: sections, uplifts, and the number at the bottom.

``Summary`` reaches its total through ``SUBTOTAL(9, D6:D14)`` over ranges that
each name a block of the cost sheet by row. That works until a band grows: the
MEP EXTERNAL heading covers rows 118 to 126, ``Summary!D11`` sums 118 to 125,
and the Substation at Rs 24,00,000 is computed, formatted and totalled into the
cost sheet's own ``I129`` while reaching the project budget through nothing
(C-38). Nothing in the workbook compares the two.

Here a section total is a filter over lines that name it, so a band cannot grow
past its total. Escalation, contingency and GST are parameters rather than
percentages typed into cells -- and typed twice at different values, which is
what ``Summary!E16 = E15*4%`` does beside ``D16 = D15*3%`` (C-42).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import ProjectModel
from ..params import ParameterSet
from ..provenance import Derived, Input, derive
from ..rules.cost_lines import PricedLine, compute_cost_lines, section_total


@dataclass
class SectionTotal:
    id: str
    code: str
    name: str
    amount: float
    lines: int
    carried: int = 0
    excel_ref: str = ""
    #: What this band folds, line by line.  A section here is a *filter* over
    #: the lines that name it, not a bounded range -- which is the structural
    #: fix for C-38, where `Summary!D11` sums I118:I125 and the MEP band runs
    #: to row 126, so Rs 24,00,000 of substation is computed and never carried.
    derivation: "Derived | None" = None

    @property
    def is_carried(self) -> bool:
        """True when every quantity here came from a sheet not modelled yet."""
        return self.lines > 0 and self.carried == self.lines


@dataclass
class Uplift:
    code: str
    label: str
    rate: float
    amount: float
    basis: str


@dataclass
class ProjectSummary:
    sections: list[SectionTotal] = field(default_factory=list)
    subtotal: float = 0.0
    uplifts: list[Uplift] = field(default_factory=list)
    before_tax: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    construction_area_sqft: float = 0.0
    derivation: Derived | None = None

    @property
    def rate_per_sqft(self) -> float | None:
        if not self.construction_area_sqft:
            return None
        return self.total / self.construction_area_sqft


def project_summary(model: ProjectModel, params: ParameterSet,
                    construction_area_sqft: float = 0.0) -> ProjectSummary:
    """Every section, then escalation, contingency and tax."""
    lines: list[PricedLine] = compute_cost_lines(model, params)

    # Sections sharing a name are one band of the estimate -- Finishing comes
    # from both cost sheets -- so they fold together the way the Summary reads.
    merged: dict[str, SectionTotal] = {}
    contributions: dict[str, list[tuple]] = {}
    for section in sorted(model.cost_sections, key=lambda s: (s.seq, s.code)):
        rows = [l for l in lines if l.line.section_id == section.id
                and not l.is_heading]
        entry = merged.get(section.name)
        if entry is None:
            entry = SectionTotal(id=section.id, code=section.code,
                                 name=section.name, amount=0.0, lines=0,
                                 excel_ref=section.excel_ref)
            merged[section.name] = entry
        entry.amount += section_total(lines, section.id)
        entry.lines += len(rows)
        entry.carried += sum(1 for l in rows if l.line.qty_carried)
        contributions.setdefault(section.name, []).extend(
            (l.line.description or l.line.id, l.amount, section.code,
             bool(l.line.qty_carried), l.line.status)
            for l in rows if l.amount)

    # The biggest lines first: a section is read to find out what is in it,
    # and twenty rows of rounding do not answer that. The tail is folded into
    # one named term so the inputs still add to the section exactly.
    for name, entry in merged.items():
        rows = sorted(contributions.get(name, []), key=lambda c: -abs(c[1]))
        inputs = []
        for description, value, code, carried, status in rows[:12]:
            source = code
            if carried:
                source += ", carried from a sheet not modelled here"
            if status and status != "priced":
                source += f", {status}"
            inputs.append(Input(description, value, source))
        rest = rows[12:]
        if rest:
            inputs.append(Input(f"{len(rest)} smaller line(s)",
                                sum(c[1] for c in rest), "the rest of the band"))
        entry.derivation = derive(
            entry.amount, "section_total",
            f"sum of {entry.lines} line(s) naming {name!r}", inputs,
            excel_ref=entry.excel_ref,
            note=(f"A filter over the lines that name this section, never a "
                  f"range of rows. {entry.carried} of {entry.lines} carry a "
                  f"quantity from a sheet not modelled here yet."
                  if entry.carried else
                  "A filter over the lines that name this section, never a "
                  "range of rows -- so a line added at the foot of the band is "
                  "counted because it names the band, not because somebody "
                  "widened a SUM (C-38)."))

    summary = ProjectSummary(sections=list(merged.values()))
    summary.subtotal = sum(s.amount for s in summary.sections)
    summary.construction_area_sqft = construction_area_sqft

    for code, label in (("escalation_pct", "Escalation"),
                        ("contingency_pct", "Contingency")):
        rate = params[code]
        summary.uplifts.append(Uplift(code, label, rate,
                                      summary.subtotal * rate,
                                      "the section subtotal"))

    summary.before_tax = summary.subtotal + sum(u.amount for u in summary.uplifts)
    gst = params["gst_pct"]
    summary.tax = summary.before_tax * gst
    summary.total = summary.before_tax + summary.tax

    summary.derivation = derive(
        summary.total, "project_total",
        f"({summary.subtotal:,.0f} + escalation + contingency) x (1 + {gst:g})",
        [Input("section subtotal", summary.subtotal, f"{len(summary.sections)} sections"),
         *[Input(u.label, u.amount, f"{u.rate:.0%} of {u.basis}")
           for u in summary.uplifts],
         Input("GST", summary.tax, f"{gst:.0%} of the pre-tax total")],
        excel_ref="Summary!D20 = SUBTOTAL(9,D6:D19)",
        note="Section totals are filters over the lines that name them, so a "
             "band cannot outgrow the range that sums it (C-38).")
    return summary
