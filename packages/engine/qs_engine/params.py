"""Named project parameters.

The workbook carries roughly forty magic numbers -- 10.764, 3.28, 1.1, 0.15,
3%, 4%, 18%, 1.12, 1.08 -- typed directly into formulas.  Two consequences:
nobody can change one safely, and nobody can say what some of them mean.
``Room Conf!AD44 = AD42*1.12`` and ``AD45 = AD44*1.08`` are live in the model
with no label, no source and no note (Q-4).

Here every such number is a named parameter with a description and a unit.  A
parameter without a description raises ``PARAMETER_UNNAMED`` in the validation
engine, which is how the 1.12/1.08 question stops being forgotten.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterator, Mapping


@dataclass(frozen=True)
class Parameter:
    key: str
    value: float
    unit: str
    description: str
    #: Where the value came from, for the derivation panel.
    source: str = ""

    @property
    def is_named(self) -> bool:
        return bool(self.description.strip())


#: Defaults reproduce the AVS workbook.  Every one is overridable per project
#: revision -- these are starting values, not constants.
DEFAULT_PARAMETERS: tuple[Parameter, ...] = (
    Parameter("factor_sqm_to_sqft", 10.764, "SQFT/SQM",
              "Square metres to square feet. The workbook's factor, not the exact "
              "10.7639, because its numbers must reproduce.",
              "Flat Sizes!E5 = D5*10.764"),
    Parameter("factor_ft_to_rm", 3.28, "RFT/RM",
              "Running feet per running metre, used to convert rates quoted per "
              "R.Ft into rates per RM.",
              "Rate List - Flats!G7 = (E7*1.1+F7)*3.28"),
    Parameter("wastage_pct", 0.10, "ratio",
              "Material wastage allowance on flooring, skirting and frames. Applied "
              "as the 1.1 in the rate build-up; deliberately NOT applied to plaster "
              "or paint (Q-6).",
              "Rate List - Flats!G6 = (E6*1.1+F6)*10.764"),
    Parameter("slab_allowance_m", 0.15, "M",
              "Slab thickness deducted from floor-to-floor height to give the clear "
              "wall height for plaster and paint.",
              "Internal Finishes Flats!E8 = D4*(D1-0.15)"),
    Parameter("frame_width_m", 0.10, "M",
              "Nominal frame width used in the frame rate build-up.",
              "Rate List - Flats!G15 = (E15*(0.1*1*1.1*10.764))+(F15*3.28)"),
    Parameter("default_floor_height_m", 3.1, "M",
              "Floor-to-floor height used for wall quantities when a room does not "
              "carry its own. The workbook hard-codes this per take-off block as "
              "D1.",
              "Internal Finishes Flats!D1 = 3.1"),
    Parameter("default_dado_height_m", 2.1, "M",
              "Dado height used when a room does not carry its own.",
              "Internal Finishes Flats!D59"),
    Parameter("escalation_pct", 0.03, "ratio",
              "Escalation applied to the pre-uplift subtotal.",
              "Summary!D16 = D15*3%"),
    Parameter("contingency_pct", 0.04, "ratio",
              "Contingency applied to the pre-uplift subtotal.",
              "Summary!D17 = D15*4%"),
    Parameter("gst_pct", 0.18, "ratio",
              "GST applied to subtotal + escalation + contingency.",
              "Summary!D19 = D18*0.18"),
    Parameter("hardscape_share_pct", 0.60, "ratio",
              "Share of the landscaped area finished as hard scape. The workbook "
              "splits it in a side calculation with 60% typed into three cells.",
              "Infra!K7 = J7*60%"),
    Parameter("softscape_share_pct", 0.40, "ratio",
              "Share finished as soft scape. Must sum with hardscape to 1.",
              "Infra!L7 = J7-K7"),
    Parameter("barrication_height_ft", 30.0, "FT",
              "Height of the site barrication, applied to the boundary wall run "
              "to give its area.",
              "Preliminary!C3 = 602.91*(30/3.28)"),
    Parameter("project_duration_months", 36.0, "MONTH",
              "Construction duration. The workbook types 36 into three separate "
              "Preliminary rows, so extending the programme means finding all "
              "three.",
              "Preliminary!C7, C10, C11"),
    Parameter("construction_area_sqft", 650726.7484, "SQFT",
              "Total construction area, the denominator of every per-sq.ft "
              "figure in the estimate. Carried from the Construction Area "
              "sheet, which this platform does not model yet -- carpet area is "
              "a different and much smaller number, and using it here would "
              "understate the rate by roughly two and a half times.",
              "Construction Area!S45"),
    Parameter("post_construction_rate_psf", 15.0, "INR/SQFT",
              "Post-construction cost per sq.ft of construction area.",
              "Summary!C14, Cost Sheet Tower!C128"),
    # Deliberately undescribed: these are Q-4.  They import with their values so
    # nothing is lost, and the validation engine reports them as unnamed until a
    # QS tells us what they are.
    Parameter("loading_factor_1", 1.12, "ratio", "", "Room Conf!AD44 = AD42*1.12"),
    Parameter("loading_factor_2", 1.08, "ratio", "", "Room Conf!AD45 = AD44*1.08"),
)


@dataclass(frozen=True)
class ParameterSet:
    """An immutable, named set of project parameters."""

    values: Mapping[str, Parameter] = field(default_factory=dict)

    @staticmethod
    def defaults() -> "ParameterSet":
        return ParameterSet({p.key: p for p in DEFAULT_PARAMETERS})

    def __getitem__(self, key: str) -> float:
        try:
            return self.values[key].value
        except KeyError:
            raise KeyError(
                f"unknown project parameter {key!r}. Parameters must be declared, "
                f"not invented at the point of use."
            ) from None

    def get(self, key: str, default: float | None = None) -> float | None:
        p = self.values.get(key)
        return p.value if p is not None else default

    def parameter(self, key: str) -> Parameter:
        return self.values[key]

    def with_value(self, key: str, value: float, *, reason: str = "") -> "ParameterSet":
        """Return a new set with ``key`` overridden.  Never mutates in place."""
        existing = self.values.get(key)
        if existing is None:
            raise KeyError(f"unknown project parameter {key!r}")
        updated = dict(self.values)
        updated[key] = replace(existing, value=value,
                               source=reason or existing.source)
        return ParameterSet(updated)

    def unnamed(self) -> tuple[Parameter, ...]:
        """Parameters with no description -- reported as ``PARAMETER_UNNAMED``."""
        return tuple(p for p in self.values.values() if not p.is_named)

    def __iter__(self) -> Iterator[Parameter]:
        return iter(self.values.values())

    def as_dict(self) -> dict[str, Any]:
        return {k: p.value for k, p in self.values.items()}
