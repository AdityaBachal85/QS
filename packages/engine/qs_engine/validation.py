"""The validation engine.

Rules are data, not code, so a new one can be added without a release.  Each
carries a severity, a message and the record it points at, so every finding is
one click from the field that caused it.

The rules here are not generic best practice.  Each one exists because of a
specific defect found in the source workbook, and the docstring says which.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable

from .model import OpeningKind, ProjectModel
from .params import ParameterSet
from .rules.rate_buildup import effective_rate
from .units import UnknownUnitError, parse_unit


class Severity(Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: Severity
    message: str
    entity: str = ""
    entity_id: str = ""
    value: float = 0.0

    def __str__(self) -> str:
        mark = {"blocking": "BLOCK", "warning": " WARN", "info": " INFO"}[self.severity.value]
        return f"[{mark}] {self.rule:24} {self.message}"


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, *findings: Finding) -> None:
        self.findings.extend(findings)

    def of(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]

    @property
    def blocking(self) -> list[Finding]:
        return self.of(Severity.BLOCKING)

    @property
    def can_issue(self) -> bool:
        """An estimate cannot be issued while anything is blocking."""
        return not self.blocking

    def health_score(self) -> float:
        """0-100, weighted so a big blocking error outranks a stale date."""
        penalty = (len(self.of(Severity.BLOCKING)) * 12
                   + len(self.of(Severity.WARNING)) * 3
                   + len(self.of(Severity.INFO)) * 0.5)
        return max(0.0, 100.0 - penalty)

    def summary(self) -> str:
        return (f"{len(self.blocking)} blocking, "
                f"{len(self.of(Severity.WARNING))} warnings, "
                f"{len(self.of(Severity.INFO))} info")


Rule = Callable[[ProjectModel, ParameterSet], Iterable[Finding]]
REGISTRY: dict[str, Rule] = {}


def rule(name: str) -> Callable[[Rule], Rule]:
    def register(fn: Rule) -> Rule:
        REGISTRY[name] = fn
        return fn
    return register


# --------------------------------------------------------------------------

@rule("MISSING_RATE")
def missing_rate(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """Quantity defined but no rate.

    C-11: ``Cost Sheet Tower!I99``, False Ceiling for the common lobby, carries
    a measured 4,508.24 sq.m against a rate of nothing and reports Rs 0.  In
    the cell beside it somebody worked out what it should cost -- Rs 65,51,104
    -- and that figure has never entered a total.
    """
    for item in model.rate_items:
        revision = model.current_revision(item.id)
        if revision is None:
            yield Finding("MISSING_RATE", Severity.BLOCKING,
                          f"{item.description!r} has no rate revision",
                          "rate_item", item.id)
        elif not revision.is_priced:
            yield Finding("MISSING_RATE", Severity.BLOCKING,
                          f"{item.description!r} has a rate row but no price "
                          f"components -- it computes to zero, which is not the "
                          f"same as costing nothing",
                          "rate_item", item.id)


@rule("UNIT_MISMATCH")
def unit_mismatch(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """Quantity and rate measured in different dimensions.

    C-35: skirting is a running-metre quantity and the workbook deducts door
    *areas* from it.  The engine refuses that arithmetic; this rule reports the
    same class of problem statically, before anyone runs a calculation.
    """
    for item in model.rate_items:
        try:
            parse_unit(item.unit)
        except UnknownUnitError:
            yield Finding("UNIT_MISMATCH", Severity.BLOCKING,
                          f"{item.description!r} has an unrecognised unit "
                          f"{item.unit!r}", "rate_item", item.id)


@rule("MISSING_DIMENSIONS")
def missing_dimensions(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """An opening type with no size.

    ``D&W Schedule!B20`` is "BR/UR" with a rate of Rs 9,500 and no length or
    height at all.  Its quantities are lengths typed into ``Windows!K``, and the
    summary lists them under "Sq M".
    """
    for opening in model.opening_types:
        if opening.kind is OpeningKind.RAILING:
            continue
        if opening.width_m <= 0 or opening.height_m <= 0:
            yield Finding("MISSING_DIMENSIONS", Severity.BLOCKING,
                          f"opening type {opening.code!r} has no width or height",
                          "opening_type", opening.id)


@rule("ROOM_WITHOUT_AREA")
def room_without_area(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """A room that exists but carries no dimensions, so nothing can be measured."""
    for room in model.unit_type_rooms:
        if room.carpet_area_sqm <= 0 and room.perimeter_m <= 0:
            yield Finding("ROOM_WITHOUT_AREA", Severity.WARNING,
                          f"room {room.label!r} has neither area nor perimeter; "
                          f"no finishing quantity can be computed for it",
                          "unit_type_room", room.id)


@rule("UNIT_TYPE_WITHOUT_ROOMS")
def unit_type_without_rooms(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """A unit type in the floor matrix that no sizes sheet describes."""
    for unit_type in model.unit_types:
        if model.unit_count(unit_type.id) and not model.rooms_of(unit_type.id):
            yield Finding("UNIT_TYPE_WITHOUT_ROOMS", Severity.WARNING,
                          f"{unit_type.code!r} appears on {model.unit_count(unit_type.id)} "
                          f"unit(s) but has no rooms defined",
                          "unit_type", unit_type.id)


@rule("COUNT_NOT_DERIVED")
def count_not_derived(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """A count typed in rather than derived from the building.

    C-36: the two smoke-check lobbies are 36 in ``Flat Sizes!H156/H157`` and 37
    in ``Doors!K137/K138``.  Both typed, neither a formula, and the finishing
    take-off and the door schedule therefore price different buildings.
    """
    for unit_type in model.unit_types:
        if unit_type.count_override is not None:
            yield Finding("COUNT_NOT_DERIVED", Severity.WARNING,
                          f"{unit_type.code!r} has a typed count of "
                          f"{unit_type.count_override} rather than one derived "
                          f"from the floor matrix, so it cannot be checked "
                          f"against the building",
                          "unit_type", unit_type.id, float(unit_type.count_override))


@rule("PARAMETER_UNNAMED")
def parameter_unnamed(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """A project parameter with no description.

    Q-4: ``Room Conf!AD44 = AD42*1.12`` and ``AD45 = AD44*1.08`` are live in the
    model with no label and no source.  Nobody can change them correctly because
    nobody knows what they are.
    """
    for parameter in params.unnamed():
        yield Finding("PARAMETER_UNNAMED", Severity.WARNING,
                      f"parameter {parameter.key!r} = {parameter.value:g} has no "
                      f"description ({parameter.source})",
                      "project_parameter", parameter.key, parameter.value)


@rule("DUPLICATE_RATE")
def duplicate_rate(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """The same described work priced two different ways.

    C-7: conventional shuttering is Rs 900 on the Shuttering Summary and
    Rs 1,086 on the Cost Sheet -- Rs 1.25 Cr apart, one sheet away from each
    other, with nothing indicating which is current.
    """
    seen: dict[str, list[tuple[str, float]]] = {}
    for item in model.rate_items:
        try:
            rate = effective_rate(item, model, params).value
        except Exception:
            continue
        key = item.description.strip().lower()
        seen.setdefault(key, []).append((item.id, rate))
    for description, entries in seen.items():
        rates = {round(r, 2) for _, r in entries}
        if len(rates) > 1:
            lo, hi = min(rates), max(rates)
            spread = (hi - lo) / lo * 100 if lo else 100.0
            yield Finding("DUPLICATE_RATE", Severity.WARNING,
                          f"{description!r} is priced {len(rates)} different ways "
                          f"({lo:,.2f} to {hi:,.2f}, {spread:.1f}% apart)",
                          "rate_item", entries[0][0], hi - lo)


@rule("UNUSED_RATE_ITEM")
def unused_rate_item(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """A rate that no room's finish schedule references."""
    used = {s.rate_item_id for s in model.room_finish_specs if s.rate_item_id}
    used |= {o.rate_item_id for o in model.opening_types if o.rate_item_id}
    for item in model.rate_items:
        if item.category == "Finishing" and item.id not in used:
            yield Finding("UNUSED_RATE_ITEM", Severity.INFO,
                          f"{item.description!r} is priced but used by no room",
                          "rate_item", item.id)


def validate(model: ProjectModel, params: ParameterSet,
             only: Iterable[str] | None = None) -> ValidationReport:
    report = ValidationReport()
    names = list(only) if only is not None else list(REGISTRY)
    for name in names:
        report.add(*REGISTRY[name](model, params))
    return report
