"""The read model: everything the UI displays, computed from the engine.

Every figure here is produced by calling into ``qs_engine``. Nothing is cached in
the database, nothing is recomputed by the UI, and there is no second
implementation of any rule. That is what makes the automation real: change one
input and every view that depends on it moves, because they all ask the engine
the same question again.
"""

from __future__ import annotations

from typing import Any

from qs_engine.model import OpeningKind, ProjectModel
from qs_engine.params import ParameterSet
from qs_engine.rules.rate_buildup import RateBuildupError, effective_rate
from qs_engine.rules.room_qty import (RULE_DEDUCTIONS, NegativeNetQuantityError,
                                      compute_room_quantity)
from qs_engine.rules.schedule import opening_schedule, total_openings
from qs_engine.rules.unit_area import (room_area_sqft, room_total_sqft,
                                       unit_type_area_sqft,
                                       unit_type_area_sqm, unit_type_total_sqft)
from qs_engine.units import UnitMismatchError
from qs_engine.validation import Severity, validate


def _derivation(derived) -> dict[str, Any]:
    d = derived.derivation
    return {
        "rule": d.rule,
        "expression": d.expression,
        "inputs": [{"name": i.name, "value": i.value, "source": i.source}
                   for i in d.inputs],
        "excel_ref": d.excel_ref,
        "note": d.note,
    }


def headline(model: ProjectModel, params: ParameterSet) -> dict[str, Any]:
    """The numbers in the top bar. Recomputed on every request, deliberately."""
    flats = sum(model.unit_count(u.id) for u in model.unit_types
                if u.is_residential and not u.is_common_area)
    offices = sum(model.unit_count(u.id) for u in model.unit_types
                  if u.classification == "Office")
    carpet = sum(unit_type_area_sqft(u.id, model, params).value * model.unit_count(u.id)
                 for u in model.unit_types if not u.is_common_area)
    report = validate(model, params)
    return {
        "project": {"id": model.project.id, "code": model.project.code,
                    "name": model.project.name, "city": model.project.city},
        "floors": len(model.floors),
        "flats": flats,
        "offices": offices,
        "classification": model.counts_by_classification(),
        "building_height_m": round(sum(f.floor_to_floor_ht for f in model.floors), 2),
        "carpet_area_sqft": carpet,
        "doors": total_openings(model, (OpeningKind.DOOR,)).value,
        "rooms": len(model.unit_type_rooms),
        "rate_items": len(model.rate_items),
        "health": {
            "score": round(validate(model, params).health_score()),
            "blocking": len(report.blocking),
            "warnings": len(report.of(Severity.WARNING)),
            "info": len(report.of(Severity.INFO)),
            "can_issue": report.can_issue,
        },
    }


def room_config(model: ProjectModel) -> dict[str, Any]:
    """The floor x unit-type matrix, plus its live totals."""
    types = sorted(model.unit_types, key=lambda u: u.seq)
    mix = {(m.floor_id, m.unit_type_id): m.count for m in model.floor_unit_mix}
    return {
        "unit_types": [
            {"id": u.id, "code": u.code, "classification": u.classification,
             "is_common_area": u.is_common_area,
             "total": model.unit_count(u.id),
             "count_override": u.count_override}
            for u in types
        ],
        "floors": [
            {"id": f.id, "seq": f.seq, "name": f.name,
             "floor_to_floor_ht": f.floor_to_floor_ht,
             "floor_type": f.floor_type.value,
             "counts": {u.id: mix.get((f.id, u.id), 0) for u in types},
             "row_total": sum(mix.get((f.id, u.id), 0) for u in types
                              if not u.is_common_area)}
            for f in sorted(model.floors, key=lambda f: f.seq)
        ],
        "classification": model.counts_by_classification(),
    }


def unit_types(model: ProjectModel, params: ParameterSet) -> list[dict[str, Any]]:
    out = []
    for u in sorted(model.unit_types, key=lambda x: x.seq):
        rooms = model.rooms_of(u.id)
        per_unit = unit_type_area_sqft(u.id, model, params)
        total = unit_type_total_sqft(u.id, model, params)
        out.append({
            "id": u.id, "code": u.code, "classification": u.classification,
            "is_common_area": u.is_common_area,
            "rooms": len(rooms),
            "count": model.unit_count(u.id),
            "area_sqm": unit_type_area_sqm(u.id, model).value,
            "area_sqft": per_unit.value,
            "total_sqft": total.value,
            "derivation": _derivation(total),
        })
    return out


def unit_rooms(model: ProjectModel, params: ParameterSet,
               unit_type_id: str) -> dict[str, Any]:
    """One unit type's rooms, with every derived figure and its openings."""
    unit = model.unit_type(unit_type_id)
    openings_by_room: dict[str, list[dict[str, Any]]] = {}
    for o in model.room_openings:
        ot = model.opening_type(o.opening_type_id)
        openings_by_room.setdefault(o.unit_type_room_id, []).append({
            "id": o.id, "code": ot.code, "kind": ot.kind.value,
            "count": o.count, "width_m": ot.width_m, "height_m": ot.height_m,
            "opening_type_id": ot.id,
        })

    rows = []
    for r in model.rooms_of(unit_type_id):
        area = room_area_sqft(r, params)
        rows.append({
            "id": r.id, "seq": r.seq, "label": r.label,
            "room_type_id": r.room_type_id,
            "room_type": model.room_type(r.room_type_id).name,
            "category": model.room_type(r.room_type_id).category.value,
            "count_per_unit": r.count_per_unit,
            "carpet_area_sqm": r.carpet_area_sqm,
            "perimeter_m": r.perimeter_m,
            "clear_height_m": r.clear_height_m,
            "area_sqft": area.value,
            "total_sqft": room_total_sqft(r, params).value,
            "derivation": _derivation(area),
            "openings": openings_by_room.get(r.id, []),
            "quantities": room_quantities(model, params, r.id),
        })
    return {
        "unit_type": {"id": unit.id, "code": unit.code,
                      "classification": unit.classification,
                      "count": model.unit_count(unit.id)},
        "rooms": rows,
        "area_sqft": unit_type_area_sqft(unit_type_id, model, params).value,
        "total_sqft": unit_type_total_sqft(unit_type_id, model, params).value,
    }


#: The finishes shown per room, in the order a QS reads them.
QUANTITY_RULES = ("floor_area", "skirting", "wall_finish", "dado",
                  "ceiling_area", "door_frame", "window_frame")


def room_quantities(model: ProjectModel, params: ParameterSet,
                    room_id: str) -> list[dict[str, Any]]:
    """Gross, deduction and net for every finish in one room.

    This is the answer to "when we give costing we minus the doors and windows,
    then skirting". The deduction is a fold over the room's own openings, so
    adding a door here changes it with no linking step -- and a deduction that
    does not match the quantity's unit raises rather than computing (C-35).
    """
    room = model.room(room_id)
    out = []
    for rule in QUANTITY_RULES:
        entry: dict[str, Any] = {"rule": rule,
                                 "deduction_rule": RULE_DEDUCTIONS.get(rule, "none")}
        try:
            q = compute_room_quantity(room, rule, model, params)
            entry.update({
                "unit": q.gross.unit.code,
                "gross": q.gross.value,
                "deduction": q.deduction.value,
                "net": q.net.value,
                "gross_derivation": _derivation(q.gross_derivation),
                "deduction_derivation": _derivation(q.deduction_derivation),
                "error": None,
            })
        except (UnitMismatchError, NegativeNetQuantityError) as exc:
            entry.update({"unit": "", "gross": None, "deduction": None,
                          "net": None, "error": str(exc)})
        out.append(entry)
    return out


def openings(model: ProjectModel) -> dict[str, Any]:
    """The door and window schedule -- a query, not a bounded range (C-18)."""
    def lines(kinds):
        return [{"code": l.code, "kind": l.kind.value, "width_m": l.width_m,
                 "height_m": l.height_m, "count": l.count,
                 "quantity": l.quantity, "unit": l.unit}
                for l in opening_schedule(model, kinds)]

    return {
        "types": [{"id": o.id, "code": o.code, "kind": o.kind.value,
                   "width_m": o.width_m, "height_m": o.height_m,
                   "area_sqm": o.area_sqm, "specification": o.specification}
                  for o in sorted(model.opening_types, key=lambda o: (o.kind.value, o.code))],
        "doors": lines((OpeningKind.DOOR,)),
        "windows": lines((OpeningKind.WINDOW, OpeningKind.VENTILATOR)),
        "railings": lines((OpeningKind.RAILING,)),
        "curtain_wall": lines((OpeningKind.CURTAIN_WALL,)),
        "total_doors": total_openings(model, (OpeningKind.DOOR,)).value,
    }


def rates(model: ProjectModel, params: ParameterSet) -> list[dict[str, Any]]:
    out = []
    for item in model.rate_items:
        revision = model.current_revision(item.id)
        row: dict[str, Any] = {
            "id": item.id, "code": item.code, "description": item.description,
            "specification": item.specification, "unit": item.unit,
            "category": item.category,
            "method": revision.method.value if revision else None,
            "basic_rate": revision.basic_rate if revision else None,
            "laying_rate": revision.laying_rate if revision else None,
            "wastage_pct": revision.wastage_pct if revision else None,
            "frame_width_m": revision.frame_width_m if revision else None,
            "is_priced": bool(revision and revision.is_priced),
            "revision_id": revision.id if revision else None,
        }
        try:
            rate = effective_rate(item, model, params)
            row["overall_rate"] = rate.value
            row["derivation"] = _derivation(rate)
        except RateBuildupError as exc:
            row["overall_rate"] = None
            row["derivation"] = None
            row["error"] = str(exc)
        out.append(row)
    return out


def validation(model: ProjectModel, params: ParameterSet) -> dict[str, Any]:
    report = validate(model, params)
    return {
        "score": round(report.health_score()),
        "summary": report.summary(),
        "can_issue": report.can_issue,
        "findings": [
            {"rule": f.rule, "severity": f.severity.value, "message": f.message,
             "entity": f.entity, "entity_id": f.entity_id, "value": f.value}
            for f in sorted(report.findings,
                            key=lambda f: {"blocking": 0, "warning": 1,
                                           "info": 2}[f.severity.value])
        ],
    }
