"""Cost lines: Infra, Amenities, Preliminary, and the cost sheets.

Four sheets with one shape -- Description, Unit, Quantity, Rate, Amount -- and
no new arithmetic. A line's amount is quantity x rate through
:func:`qs_engine.units.amount`, which refuses to multiply across dimensions, so
a lump sum cannot be priced per square metre.

Three things the workbook does that stop being possible here:

* **A typed amount in a computed column.** ``Infra!E5`` holds 1,000,000 and
  ``E12`` holds 1,500,000 where every neighbour is ``=C*D`` (C-33). Both become
  ``1 LS x rate``, so the arithmetic is visible and the rate is a rate.
* **A total that stops short of its data.** ``Summary!D11`` sums
  ``I118:I125`` while the band it totals runs to row 126, so the Substation at
  Rs 24,00,000 reaches no total at all (C-38). Sections here are filters.
* **A quantity hidden in a side calculation.** ``Infra!C9`` is ``=K10``, and
  K10 is 60% of three areas summed in a corner of the sheet. The components
  become rows and the 60% becomes a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import CostLine, LineStatus, ProjectModel
from ..params import ParameterSet
from ..provenance import Derived, Input, derive
from ..units import (Quantity, Rate, UnitConverter, UnitMismatchError, amount,
                     parse_unit)


class CostLineError(Exception):
    """A line that cannot be priced as configured."""


@dataclass
class PricedLine:
    """One cost line, priced, with its working."""

    line: CostLine
    description: str
    unit: str
    qty: float
    rate: float | None
    amount: float
    status: str
    depth: int = 0
    is_heading: bool = False
    message: str = ""
    qty_derivation: Derived | None = field(default=None, repr=False)
    rate_derivation: Derived | None = field(default=None, repr=False)

    @property
    def counts(self) -> bool:
        """Whether this line's amount belongs in a total.

        A heading does not -- its amount is its children, already counted. An
        excluded line does not either, but it keeps its value and its reason
        rather than being multiplied by zero (C-2).
        """
        return not self.is_heading and self.status != LineStatus.EXCLUDED.value


def line_quantity(line: CostLine, model: ProjectModel,
                  params: ParameterSet) -> Derived:
    """A line's quantity: typed, or folded from its components.

    Components carry a share that names a parameter, so the hard/soft landscape
    split is one number in one place instead of 60% typed into three cells.
    """
    components = model.qty_components(line.id)
    if not components:
        return derive(float(line.qty or 0.0), "cost_qty",
                      f"{line.qty or 0:g}",
                      [Input("qty", line.qty or 0.0, line.source_ref or "entered")],
                      excel_ref=line.source_ref)

    total = 0.0
    inputs: list[Input] = []
    parts: list[str] = []
    for component in components:
        share = (params[component.factor_param_key]
                 if component.factor_param_key else component.factor)
        contribution = component.value * share
        total += contribution
        inputs.append(Input(component.label, contribution,
                            f"{component.value:g} x {share:g}"
                            + (f" [{component.factor_param_key}]"
                               if component.factor_param_key else "")))
        parts.append(f"{component.value:g}x{share:g}")
    return derive(total, "cost_qty_components", " + ".join(parts), inputs,
                  note="folded from its components, not typed")


def line_rate(line: CostLine, model: ProjectModel,
              params: ParameterSet) -> Derived | None:
    """The rate on a line: from the library, or carried on the line itself."""
    if line.rate_item_id:
        from ..rules.rate_buildup import effective_rate
        return effective_rate(model.rate_item(line.rate_item_id), model, params)
    if line.manual_rate is not None:
        return derive(float(line.manual_rate), "cost_rate",
                      f"{line.manual_rate:g}",
                      [Input("rate", line.manual_rate,
                             line.source_ref or "entered")],
                      excel_ref=line.source_ref)
    return None


def price_line(line: CostLine, model: ProjectModel, params: ParameterSet,
               converter: UnitConverter | None = None) -> PricedLine:
    """One line, priced through the unit-safe path."""
    converter = converter or UnitConverter(params["factor_sqm_to_sqft"],
                                           params["factor_ft_to_rm"])
    depth = 1 if line.parent_id else 0

    if line.is_heading:
        return PricedLine(line=line, description=line.description, unit="",
                          qty=0.0, rate=None, amount=0.0,
                          status=line.status.value, depth=depth, is_heading=True)

    qty_d = line_quantity(line, model, params)
    rate_d = line_rate(line, model, params)
    base = dict(line=line, description=line.description, unit=line.unit,
                qty=qty_d.value, rate=rate_d.value if rate_d else None,
                amount=0.0, status=line.status.value, depth=depth,
                qty_derivation=qty_d, rate_derivation=rate_d)

    if rate_d is None:
        return PricedLine(**{**base, "message": (
            f"{line.description} is measured but carries no rate -- that is a "
            f"missing price, not a zero cost")})

    try:
        value = amount(Quantity.of(qty_d.value, parse_unit(line.unit or "LS")),
                       Rate.of(rate_d.value, parse_unit(line.unit or "LS")),
                       converter)
    except UnitMismatchError as exc:
        return PricedLine(**{**base, "message": str(exc)})

    return PricedLine(**{**base, "amount": value})


def compute_cost_lines(model: ProjectModel, params: ParameterSet,
                       section_id: str | None = None) -> list[PricedLine]:
    """Every cost line, priced, in reading order with headings in place."""
    converter = UnitConverter(params["factor_sqm_to_sqft"],
                              params["factor_ft_to_rm"])
    sections = ([s for s in model.cost_sections if s.id == section_id]
                if section_id else sorted(model.cost_sections, key=lambda s: s.seq))

    out: list[PricedLine] = []
    for section in sections:
        for line in model.lines_of(section.id):
            if line.parent_id:
                continue                       # emitted under its heading
            priced = price_line(line, model, params, converter)
            children = [price_line(c, model, params, converter)
                        for c in model.children_of(line.id)]
            if priced.is_heading:
                priced.amount = sum(c.amount for c in children
                                    if c.status != LineStatus.EXCLUDED.value)
            out.append(priced)
            out.extend(children)
    return out


def section_total(lines: list[PricedLine], section_id: str) -> float:
    """One section's cost. A filter over lines, never a range over rows."""
    return sum(l.amount for l in lines
               if l.line.section_id == section_id
               and not l.is_heading
               and l.status != LineStatus.EXCLUDED.value)


def total_cost(lines: list[PricedLine]) -> float:
    return sum(l.amount for l in lines
               if not l.is_heading and l.status != LineStatus.EXCLUDED.value)


def excluded(lines: list[PricedLine]) -> list[PricedLine]:
    """Lines carrying a value and a reason for not counting (C-2)."""
    return [l for l in lines if l.status == LineStatus.EXCLUDED.value]


def unpriced(lines: list[PricedLine]) -> list[PricedLine]:
    return [l for l in lines if not l.is_heading and l.rate is None]
