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

    #: The most each severity class can take off the score.
    #:
    #: A flat penalty per finding saturates: 47 warnings at 3 points each is
    #: 141, which clamps to zero, and from there 47 warnings and 470 look
    #: identical -- the number stops carrying information exactly when there is
    #: most to say. Capping each class keeps blocking findings dominant while
    #: leaving warnings able to move the figure.
    _CAPS = ((Severity.BLOCKING, 12.0, 60.0),
             (Severity.WARNING, 3.0, 30.0),
             (Severity.INFO, 0.5, 10.0))

    def health_score(self) -> float:
        """0-100, weighted so a blocking error outranks a stale date.

        100 means nothing at all was found. Blocking findings can take it to 40
        on their own; warnings and information cannot drive it below 60 between
        them, because a pile of notes is not the same as a broken estimate.
        """
        penalty = sum(min(len(self.of(severity)) * each, cap)
                      for severity, each, cap in self._CAPS)
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

#: What a rate list writes in the specification column when a finish does not
#: apply to a room at all -- a bedroom has no dado, a duct has no flooring.
_NOT_APPLICABLE = {"N.A", "NA", "N/A", "NOT APPLICABLE"}


def not_applicable(item) -> bool:
    """True when the rate list says this finish does not apply to the room.

    100 rows carry it (79 in the flats list, 21 in the office list) and the
    take-off tests it 1,790 times as ``IF(I5="N.A",0,...)``.  Without this,
    every one of them was reported as a *missing price* -- work somebody forgot
    to cost -- which is a different thing entirely, and the false alarms buried
    the four real ones.
    """
    return " ".join(str(item.specification or "").split()).upper().rstrip(".") \
        in {s.rstrip(".") for s in _NOT_APPLICABLE}


@rule("EXCLUDED_BY_SPEC")
def excluded_by_spec(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """Finishes the rate list marks "N.A." for a room.

    Reported rather than silently dropped: an exclusion carries a reason and
    keeps its row (C-2). The workbook's own take-off already computes zero for
    these, so nothing here changes a number -- it changes what the finding is
    called.
    """
    slots = {s.id: s for s in model.finish_slots}
    for spec in model.room_finish_specs:
        if not spec.rate_item_id:
            continue
        try:
            item = model.rate_item(spec.rate_item_id)
        except KeyError:
            continue
        if not not_applicable(item):
            continue
        slot = slots.get(spec.finish_slot_id)
        room = model.room_type(spec.room_type_id)
        yield Finding("EXCLUDED_BY_SPEC", Severity.INFO,
                      f"{slot.name if slot else 'finish'} does not apply to "
                      f"{room.name} -- the rate list specification reads "
                      f"'N.A.'. Not an unpriced item.",
                      "finish_spec", spec.id)


@rule("DUPLICATE_FINISH_SCHEDULE")
def duplicate_finish_schedule(model: ProjectModel,
                              params: ParameterSet) -> Iterable[Finding]:
    """One room type carrying the same finish slot twice.

    ``Lift Lobby``, ``Lift Shaft`` and ``Staircase Area`` each head a block in
    *both* rate lists, with different specifications -- one says Dado is N.A.,
    the other prices it -- and both fold into one room type, so every room
    priced on it picks up the slot twice.

    Deliberately reported rather than merged or split. Splitting them moves the
    finishing take-off 16% away from the workbook, which means the workbook is
    counting something here that this reading does not explain, and a number
    nobody can explain must not be changed quietly.
    """
    seen: dict[tuple[str, str], int] = {}
    for spec in model.room_finish_specs:
        key = (spec.room_type_id, spec.finish_slot_id)
        seen[key] = seen.get(key, 0) + 1

    slots = {s.id: s for s in model.finish_slots}
    for (room_type_id, slot_id), count in sorted(seen.items()):
        if count < 2:
            continue
        slot = slots.get(slot_id)
        room = model.room_type(room_type_id)
        rooms = sum(1 for r in model.unit_type_rooms
                    if model.pricing_room_type(r.room_type_id) == room_type_id)
        yield Finding("DUPLICATE_FINISH_SCHEDULE", Severity.WARNING,
                      f"{room.name} carries {count} "
                      f"{slot.name if slot else 'finish'} rows, from two rate "
                      f"blocks of the same name. {rooms} room(s) are priced on "
                      f"it, so the slot is applied {count} times.",
                      "room_type", room_type_id, value=count)


@rule("MISSING_RATE")
def missing_rate(model: ProjectModel, params: ParameterSet) -> Iterable[Finding]:
    """Quantity defined but no rate.

    C-11: ``Cost Sheet Tower!I99``, False Ceiling for the common lobby, carries
    a measured 4,508.24 sq.m against a rate of nothing and reports Rs 0.  In
    the cell beside it somebody worked out what it should cost -- Rs 65,51,104
    -- and that figure has never entered a total.
    """
    for item in model.rate_items:
        if not_applicable(item):
            continue          # reported by EXCLUDED_BY_SPEC, not missing a price
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
