"""Unit registry and unit-safe quantity arithmetic.

This module exists because of a defect found in the source workbook (C-35):
``Internal Finishes Flats!F6`` deducts ``Doors!H5+H6+H7+H9`` -- door *areas*, in
sq.m -- from a skirting quantity measured in running metres.  Every door in the
schedule is 2.1 m high, so the deduction is exactly 2.1x too large, and
1,448.23 RM of skirting across the building is never priced (Rs 5,67,648 at
``Rate List - Flats!G7``).

Excel cannot see that mistake: a number is a number.  Here a quantity carries
its unit, and combining incompatible dimensions raises rather than computing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class Dimension(Enum):
    """What a unit measures.  Addition is only ever legal within a dimension."""

    LENGTH = "length"
    AREA = "area"
    VOLUME = "volume"
    MASS = "mass"
    COUNT = "count"
    LUMPSUM = "lumpsum"
    DURATION = "duration"
    CURRENCY = "currency"
    RATIO = "ratio"


class UnitMismatchError(Exception):
    """Raised when two quantities of different dimensions are combined."""


class UnknownUnitError(Exception):
    """Raised when a unit string cannot be resolved to a registered unit."""


@dataclass(frozen=True)
class Unit:
    code: str
    name: str
    dimension: Dimension
    #: How many of this unit make up one base unit of the dimension.  ``None``
    #: means the ratio is a project parameter rather than a physical constant
    #: (see :class:`UnitConverter`), which is the case for every imperial/metric
    #: pair here -- the workbook uses 10.764 and 3.28, not the exact values, and
    #: reproducing its numbers requires using *its* factors.
    per_base: float | None = None


_UNIT_LIST: tuple[Unit, ...] = (
    Unit("M", "Metre", Dimension.LENGTH, 1.0),
    Unit("RM", "Running metre", Dimension.LENGTH, 1.0),
    Unit("FT", "Foot", Dimension.LENGTH, None),
    Unit("RFT", "Running foot", Dimension.LENGTH, None),
    Unit("SQM", "Square metre", Dimension.AREA, 1.0),
    Unit("SQFT", "Square foot", Dimension.AREA, None),
    Unit("CUM", "Cubic metre", Dimension.VOLUME, 1.0),
    Unit("CUFT", "Cubic foot", Dimension.VOLUME, None),
    Unit("KG", "Kilogram", Dimension.MASS, 1.0),
    Unit("TON", "Metric tonne", Dimension.MASS, 0.001),
    Unit("NOS", "Number", Dimension.COUNT, 1.0),
    Unit("LS", "Lump sum", Dimension.LUMPSUM, 1.0),
    # Preliminaries are billed by time: 36 months of site establishment at
    # Rs 25,000. per_base is None on the smaller units so nothing silently
    # turns 36 months into 1,095 days -- a month is not a fixed number of them.
    Unit("MONTH", "Month", Dimension.DURATION, 1.0),
    Unit("WEEK", "Week", Dimension.DURATION, None),
    Unit("DAY", "Day", Dimension.DURATION, None),
    Unit("INR", "Indian rupee", Dimension.CURRENCY, 1.0),
    Unit("PCT", "Percent", Dimension.RATIO, 1.0),
)

UNITS: Mapping[str, Unit] = {u.code: u for u in _UNIT_LIST}

#: Spelling variants seen in the workbook, normalised to a registered code.
#: ``Rate List - Flats`` alone writes "Sq Ft", "Sq.Ft", "SQ FT" and "sqft".
_ALIASES: Mapping[str, str] = {
    "SQM": "SQM", "SQ M": "SQM", "SQ.M": "SQM", "SQMT": "SQM", "M2": "SQM",
    "SQFT": "SQFT", "SQ FT": "SQFT", "SQ.FT": "SQFT", "FT2": "SQFT",
    "RM": "RM", "R M": "RM", "RMT": "RM", "MTR": "M", "M": "M", "METRE": "M",
    "RFT": "RFT", "R FT": "RFT", "R.FT": "RFT", "RUNNING FT": "RFT",
    "FT": "FT", "FEET": "FT", "FOOT": "FT",
    "CUM": "CUM", "CU M": "CUM", "CU.M": "CUM", "M3": "CUM",
    "CUFT": "CUFT", "CU FT": "CUFT", "CU.FT": "CUFT",
    "KG": "KG", "MT": "TON", "TON": "TON", "TONNE": "TON", "TONNES": "TON", "T": "TON",
    "NOS": "NOS", "NO": "NOS", "NO.": "NOS", "NOS.": "NOS", "NUMBER": "NOS", "EACH": "NOS",
    "LS": "LS", "L S": "LS", "LUMPSUM": "LS", "LUMP SUM": "LS", "L.S.": "LS",
    "INR": "INR", "RS": "INR", "RS.": "INR",
    "MONTH": "MONTH", "MONTHS": "MONTH", "MTH": "MONTH", "MNTH": "MONTH",
    "WEEK": "WEEK", "WEEKS": "WEEK", "DAY": "DAY", "DAYS": "DAY",
    "PCT": "PCT", "%": "PCT",
}


def parse_unit(raw: str | Unit | None) -> Unit:
    """Resolve a unit string as written in the workbook to a registered unit.

    Tolerant of case, internal punctuation and stray whitespace -- the source
    data has all three -- but never guesses: an unrecognised string raises
    rather than silently defaulting, because a wrong unit is exactly the
    failure this module exists to prevent.
    """
    if isinstance(raw, Unit):
        return raw
    if raw is None:
        raise UnknownUnitError("unit is required, got None")
    key = re.sub(r"\s+", " ", str(raw).strip().upper())
    if key in UNITS:
        return UNITS[key]
    if key in _ALIASES:
        return UNITS[_ALIASES[key]]
    compact = key.replace(".", "").replace(" ", "")
    for candidate in (compact, compact.rstrip("S")):
        if candidate in UNITS:
            return UNITS[candidate]
        if candidate in _ALIASES:
            return UNITS[_ALIASES[candidate]]
    raise UnknownUnitError(f"unrecognised unit {raw!r}")


class UnitConverter:
    """Converts between units using *project parameters*, not physical constants.

    The workbook converts sq.m to sq.ft with 10.764 and R.ft to RM with 3.28.
    Those are the numbers that must be reproduced, so they live in the parameter
    set and are passed in here rather than being baked into the code.
    """

    def __init__(self, sqm_to_sqft: float, ft_to_rm: float) -> None:
        self.sqm_to_sqft = sqm_to_sqft
        self.ft_to_rm = ft_to_rm

    def factor(self, frm: Unit, to: Unit) -> float:
        """Multiplier taking a quantity in ``frm`` to the same quantity in ``to``."""
        if frm.dimension is not to.dimension:
            raise UnitMismatchError(
                f"cannot convert {frm.code} ({frm.dimension.value}) to "
                f"{to.code} ({to.dimension.value})"
            )
        if frm.code == to.code:
            return 1.0
        return self._to_base(frm) / self._to_base(to)

    def _to_base(self, unit: Unit) -> float:
        """How many base units one ``unit`` is worth."""
        if unit.per_base is not None:
            return 1.0 / unit.per_base if unit.dimension is Dimension.MASS else unit.per_base
        if unit.code == "SQFT":
            return 1.0 / self.sqm_to_sqft
        if unit.code in ("FT", "RFT"):
            return 1.0 / self.ft_to_rm
        if unit.code == "CUFT":
            return 1.0 / (self.sqm_to_sqft ** 1.5)
        raise UnknownUnitError(f"no conversion basis for {unit.code}")

    def convert(self, value: float, frm: Unit | str, to: Unit | str) -> float:
        return value * self.factor(parse_unit(frm), parse_unit(to))


@dataclass(frozen=True)
class Quantity:
    """A number that knows what it measures.

    Addition and subtraction require a matching dimension.  This is what turns
    C-35 from an invisible 2.1x error into a loud failure at the moment the
    deduction is applied.
    """

    value: float
    unit: Unit

    @staticmethod
    def of(value: float, unit: str | Unit) -> "Quantity":
        return Quantity(float(value), parse_unit(unit))

    def _check(self, other: "Quantity", op: str) -> None:
        if self.unit.dimension is not other.unit.dimension:
            raise UnitMismatchError(
                f"cannot {op} {other.value:g} {other.unit.code} "
                f"({other.unit.dimension.value}) and {self.value:g} {self.unit.code} "
                f"({self.unit.dimension.value})"
            )

    def to(self, unit: str | Unit, converter: UnitConverter) -> "Quantity":
        target = parse_unit(unit)
        return Quantity(self.value * converter.factor(self.unit, target), target)

    def add(self, other: "Quantity", converter: UnitConverter | None = None) -> "Quantity":
        self._check(other, "add")
        rhs = other if other.unit.code == self.unit.code else other.to(self.unit, _require(converter))
        return Quantity(self.value + rhs.value, self.unit)

    def subtract(self, other: "Quantity", converter: UnitConverter | None = None) -> "Quantity":
        self._check(other, "subtract")
        rhs = other if other.unit.code == self.unit.code else other.to(self.unit, _require(converter))
        return Quantity(self.value - rhs.value, self.unit)

    def scale(self, factor: float) -> "Quantity":
        return Quantity(self.value * factor, self.unit)

    def __add__(self, other: "Quantity") -> "Quantity":
        return self.add(other)

    def __sub__(self, other: "Quantity") -> "Quantity":
        return self.subtract(other)

    def __str__(self) -> str:
        return f"{self.value:,.4f} {self.unit.code}"


def _require(converter: UnitConverter | None) -> UnitConverter:
    if converter is None:
        raise UnitMismatchError(
            "units differ and no converter was supplied; conversion must be explicit"
        )
    return converter


@dataclass(frozen=True)
class Rate:
    """A price per unit of something.  ``1340.118 INR per SQM``."""

    value: float
    per: Unit

    @staticmethod
    def of(value: float, per: str | Unit) -> "Rate":
        return Rate(float(value), parse_unit(per))

    def __str__(self) -> str:
        return f"INR {self.value:,.4f}/{self.per.code}"


def amount(qty: Quantity, rate: Rate, converter: UnitConverter | None = None) -> float:
    """Quantity x rate, in rupees, refusing to multiply mismatched units.

    Engine invariant 6: ``unit_of(quantity) == unit_of(rate)`` for every priced
    line.  A quantity in RM priced against a rate per SQM is a defect, not a
    number.
    """
    if qty.unit.dimension is not rate.per.dimension:
        raise UnitMismatchError(
            f"quantity is in {qty.unit.code} ({qty.unit.dimension.value}) but the rate "
            f"is per {rate.per.code} ({rate.per.dimension.value})"
        )
    q = qty if qty.unit.code == rate.per.code else qty.to(rate.per, _require(converter))
    return q.value * rate.value
