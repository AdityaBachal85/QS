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
from qs_engine.rules.schedule import (opening_schedule, opening_totals,
                                      priced_opening_schedule,
                                      total_opening_amount, total_openings)
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
            "score": round(report.health_score()),
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

    # Wall quantities depend on the floor the unit sits on, so this view has to
    # resolve the same height the take-off does -- otherwise the two screens
    # would report different walls for one room, which is the class of defect
    # this platform exists to remove. Where a type spans floors of different
    # heights the rooms are shown at the predominant one, and every height is
    # reported alongside so the split is visible rather than averaged away.
    placements = model.height_placements(unit_type_id)
    dominant = max(placements, key=lambda p: p.count) if placements else None
    floor_height_m = dominant.height_m if dominant else None

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
            "quantities": room_quantities(model, params, r.id, floor_height_m),
        })
    return {
        "unit_type": {"id": unit.id, "code": unit.code,
                      "classification": unit.classification,
                      "count": model.unit_count(unit.id)},
        "floor_height_m": floor_height_m,
        "heights": [{"height_m": p.height_m, "count": p.count,
                     "floors": list(p.floors)} for p in placements],
        "rooms": rows,
        "area_sqft": unit_type_area_sqft(unit_type_id, model, params).value,
        "total_sqft": unit_type_total_sqft(unit_type_id, model, params).value,
    }


#: The finishes shown per room, in the order a QS reads them.
QUANTITY_RULES = ("floor_area", "skirting", "wall_finish", "dado",
                  "ceiling_area", "door_frame", "window_frame")


def room_quantities(model: ProjectModel, params: ParameterSet,
                    room_id: str,
                    floor_height_m: float | None = None) -> list[dict[str, Any]]:
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
            q = compute_room_quantity(room, rule, model, params,
                                      floor_height_m=floor_height_m)
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


# --------------------------------------------------------------------------
# The finishing take-off -- where quantities meet rates
# --------------------------------------------------------------------------

def _line_json(line, *, working: bool = False) -> dict[str, Any]:
    """One take-off line.

    ``working`` carries the three derivation blocks. They are 54% of the
    payload and a QS opens one at a time, so the list omits them and the
    derivation route serves whichever is clicked.
    """
    out = {
        "unit_type_id": line.unit_type_id, "unit_type": line.unit_type_code,
        "room_id": line.room_id, "room": line.room_label,
        "finish": line.finish_name, "finish_slot_id": line.finish_slot_id,
        "rule": line.qty_rule, "unit": line.unit,
        "gross": line.gross, "deduction": line.deduction, "net": line.net,
        "unit_count": line.unit_count, "total_qty": line.total_qty,
        "rate_item_id": line.rate_item_id, "rate_description": line.rate_description,
        "rate": line.rate, "amount_per_unit": line.amount_per_unit,
        "total_amount": line.total_amount,
        "status": line.status, "message": line.message,
        "floor_height_m": line.floor_height_m, "floor_scope": line.floor_scope,
    }
    if working:
        out.update({
            "gross_derivation": _derivation(line.gross_derivation)
            if line.gross_derivation else None,
            "deduction_derivation": _derivation(line.deduction_derivation)
            if line.deduction_derivation else None,
            "rate_derivation": _derivation(line.rate_derivation)
            if line.rate_derivation else None,
        })
    return out


def takeoff_derivation(model: ProjectModel, params: ParameterSet, room_id: str,
                       finish_slot_id: str, unit_type_id: str | None = None,
                       floor_height_m: float | None = None) -> dict[str, Any] | None:
    """The working behind one figure, fetched when somebody clicks it."""
    from qs_engine.rules.takeoff import compute_takeoff

    for line in compute_takeoff(model, params, unit_type_id):
        if line.room_id != room_id or line.finish_slot_id != finish_slot_id:
            continue
        if floor_height_m is not None and line.floor_height_m != floor_height_m:
            continue
        return _line_json(line, working=True)
    return None


def _group_json(groups) -> list[dict[str, Any]]:
    return [{"key": g.key, "label": g.label, "unit": g.unit,
             "quantity": g.quantity, "quantity_sqft": g.quantity_sqft,
             "amount": g.amount, "lines": g.lines, "unpriced": g.unpriced,
             "blended_rate": g.blended_rate,
             "rate_per_sqft": g.rate_per_sqft} for g in groups]


def takeoff(model: ProjectModel, params: ParameterSet,
            unit_type_id: str | None = None) -> dict[str, Any]:
    """Every finish in every room, priced.

    Replaces 1,451 hand-written rows in ``Internal Finishes Flats``. The totals
    are folds over a filter, so a finish added tomorrow is included because it
    matches, not because a range was widened.
    """
    from qs_engine.rules.takeoff import (by_finish, by_unit_type, compute_takeoff,
                                         total_amount, unpriced)

    lines = compute_takeoff(model, params, unit_type_id)
    missing = unpriced(lines)
    return {
        "lines": [_line_json(l) for l in lines],
        "by_finish": _group_json(by_finish(lines, params)),
        "by_unit_type": _group_json(by_unit_type(lines, params)),
        "total": total_amount(lines),
        "line_count": len(lines),
        "priced_count": sum(1 for l in lines if l.is_priced),
        "unpriced": [_line_json(l) for l in missing],
        "unpriced_qty": sum(l.total_qty for l in missing),
    }


def room_costs(model: ProjectModel, params: ParameterSet,
               unit_type_id: str) -> dict[str, list[dict[str, Any]]]:
    """Take-off lines for one unit type, keyed by room.

    This is what puts a rate beside every quantity on the Unit Types screen.
    """
    from qs_engine.rules.takeoff import compute_takeoff

    out: dict[str, list[dict[str, Any]]] = {}
    for line in compute_takeoff(model, params, unit_type_id):
        out.setdefault(line.room_id, []).append(_line_json(line, working=True))
    return out


def room_type_mapping(model: ProjectModel,
                      params: ParameterSet) -> list[dict[str, Any]]:
    """Which rate block prices each room type, and whether anyone has agreed.

    The sizes sheets and the rate list name rooms differently -- ``M. Bedroom``
    against ``M. Bed``, ``M. Toilet`` against ``Toilet With M. Bed``. Only six of
    twenty-five match by name, so without this every other room is measured and
    unpriced.
    """
    from qs_engine.rules.takeoff import by_room_type, compute_takeoff

    used = {r.room_type_id for r in model.unit_type_rooms}
    priced = {s.room_type_id for s in model.room_finish_specs}
    rooms_per_type: dict[str, int] = {}
    for room in model.unit_type_rooms:
        rooms_per_type[room.room_type_id] = rooms_per_type.get(room.room_type_id, 0) + 1

    # What each link is currently worth, so agreeing to one is an informed
    # decision rather than a shrug.
    worth = {g.key: g.amount for g in by_room_type(compute_takeoff(model, params))}

    out = []
    for room_type in sorted(model.room_types, key=lambda t: t.name):
        if room_type.id not in used:
            continue
        target_id = model.pricing_room_type(room_type.id)
        target = model.room_type(target_id) if target_id else None
        out.append({
            "id": room_type.id, "name": room_type.name,
            "category": room_type.category.value,
            "rooms": rooms_per_type.get(room_type.id, 0),
            "prices_as_id": room_type.prices_as_id,
            "prices_as": target.name if target else "",
            "confirmed": room_type.mapping_confirmed,
            "own_schedule": room_type.id in priced,
            "finishes": len(model.finish_spec_for(room_type.id)),
            "amount": worth.get(room_type.id, 0.0),
        })
    return out


def priceable_room_types(model: ProjectModel) -> list[dict[str, str]]:
    """The room types that carry a finish schedule -- the dropdown for mapping."""
    priced = {s.room_type_id for s in model.room_finish_specs}
    return [{"value": t.id, "label": t.name}
            for t in sorted(model.room_types, key=lambda t: t.name)
            if t.id in priced]


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


# --------------------------------------------------------------------------
# Totals -- the whole building in one view
# --------------------------------------------------------------------------

def opening_costs(model: ProjectModel, params: ParameterSet) -> dict[str, Any]:
    """Every door, window, railing and curtain-wall bay, counted and priced.

    Counts were always folded correctly here; the money is new. A door is
    priced by the leaf and glazing by the square metre, and the multiplication
    goes through the unit-safe path, so a per-Nos. rate cannot be applied to an
    area.
    """
    lines = priced_opening_schedule(model, params)
    return {
        "lines": [{
            "code": l.code, "kind": l.kind.value,
            "width_m": l.width_m, "height_m": l.height_m,
            "count": l.count, "quantity": l.quantity, "unit": l.unit,
            "rate": l.rate, "rate_unit": l.rate_unit,
            "rate_item_id": l.rate_item_id,
            "rate_description": l.rate_description,
            "amount": l.amount, "status": l.status, "message": l.message,
        } for l in lines],
        "bands": [{
            "key": b.key, "label": b.label, "unit": b.unit, "count": b.count,
            "quantity": b.quantity, "amount": b.amount, "lines": b.lines,
            "unpriced": b.unpriced,
        } for b in opening_totals(model, params)],
        "total": total_opening_amount(model, params),
        "total_count": sum(l.count for l in lines),
        "unpriced": [{"code": l.code, "message": l.message}
                     for l in lines if not l.is_priced],
    }


def finish_totals(model: ProjectModel, params: ParameterSet) -> dict[str, Any]:
    """The building's finishing, folded three ways.

    By finish, by room type, and by the two together -- "total flooring area in
    toilets" is one cell of the last. All three are filters over the same
    take-off lines, so they cannot disagree with each other or with the
    per-room views.
    """
    from qs_engine.rules.takeoff import (by_finish, by_finish_and_room_type,
                                         by_room_type, by_unit_type,
                                         compute_takeoff, total_amount)

    lines = compute_takeoff(model, params)
    total = total_amount(lines)
    carpet = sum(unit_type_area_sqft(u.id, model, params).value * model.unit_count(u.id)
                 for u in model.unit_types if not u.is_common_area)

    contributors: dict[str, list[dict[str, Any]]] = {}
    for group in by_finish(lines, params):
        rows = [l for l in lines if l.finish_slot_id == group.key]
        per_unit: dict[str, dict[str, Any]] = {}
        for line in rows:
            entry = per_unit.setdefault(line.unit_type_id, {
                "unit_type_id": line.unit_type_id, "label": line.unit_type_code,
                "quantity": 0.0, "amount": 0.0, "unit": line.unit})
            entry["quantity"] += line.total_qty
            entry["amount"] += line.total_amount
        contributors[group.key] = sorted(per_unit.values(),
                                         key=lambda e: -e["amount"])

    return {
        "by_finish": _group_json(by_finish(lines, params)),
        "by_room_type": _group_json(by_room_type(lines, params)),
        "matrix": _group_json(by_finish_and_room_type(lines, params)),
        "by_unit_type": _group_json(by_unit_type(lines, params)),
        "contributors": contributors,
        "total": total,
        "openings_total": total_opening_amount(model, params),
        "carpet_area_sqft": carpet,
        "rate_per_carpet_sqft": (total / carpet) if carpet else None,
        "line_count": len(lines),
        "unit_types": len({l.unit_type_id for l in lines}),
    }


def usage(model: ProjectModel, params: ParameterSet, kind: str,
          subject: str) -> dict[str, Any]:
    """Where a value is used -- the question provenance cannot answer.

    "If I change this, what moves?" The workbook has no way to ask it: 10.764
    is typed into hundreds of formulas with nothing linking them, which is why
    nobody dares touch one.
    """
    from qs_engine.rules import usage as U

    finder = {"parameter": U.parameter_usage, "rate": U.rate_usage,
              "room": U.room_usage}.get(kind)
    if finder is None:
        raise KeyError(f"cannot look up usage of a {kind!r}")

    found = finder(subject, model, params)
    return {
        "subject": found.subject, "kind": found.kind,
        "description": found.description, "note": found.note,
        "total_amount": found.total_amount, "total_lines": found.total_lines,
        "uses": [{"where": u.where, "detail": u.detail, "quantity": u.quantity,
                  "unit": u.unit, "amount": u.amount} for u in found.uses],
    }


# --------------------------------------------------------------------------
# Cost lines and the project roll-up
# --------------------------------------------------------------------------

def _priced_line_json(p) -> dict[str, Any]:
    return {
        "id": p.line.id, "section_id": p.line.section_id,
        "description": p.description, "unit": p.unit, "qty": p.qty,
        "rate": p.rate, "amount": p.amount, "status": p.status,
        "depth": p.depth, "is_heading": p.is_heading, "message": p.message,
        "source_ref": p.line.source_ref, "qty_carried": p.line.qty_carried,
        "exclusion_reason": p.line.exclusion_reason,
        "rate_item_id": p.line.rate_item_id, "manual_rate": p.line.manual_rate,
        "qty_derivation": _derivation(p.qty_derivation) if p.qty_derivation else None,
        "rate_derivation": _derivation(p.rate_derivation) if p.rate_derivation else None,
    }


def cost_lines(model: ProjectModel, params: ParameterSet) -> dict[str, Any]:
    """Every cost line, priced, grouped by the section that owns it."""
    from qs_engine.rules.cost_lines import (compute_cost_lines, excluded,
                                            section_total, total_cost, unpriced)

    lines = compute_cost_lines(model, params)
    return {
        "sections": [{
            "id": s.id, "code": s.code, "name": s.name, "seq": s.seq,
            "excel_ref": s.excel_ref,
            "amount": section_total(lines, s.id),
            "lines": [_priced_line_json(l) for l in lines
                      if l.line.section_id == s.id],
        } for s in sorted(model.cost_sections, key=lambda x: (x.seq, x.code))],
        "total": total_cost(lines),
        "excluded": [_priced_line_json(l) for l in excluded(lines)],
        "unpriced": [_priced_line_json(l) for l in unpriced(lines)],
    }


def project_summary(model: ProjectModel, params: ParameterSet) -> dict[str, Any]:
    """The number at the bottom, and everything that makes it."""
    from qs_engine.rules.summary import project_summary as compute

    # The workbook divides by construction area (Construction Area!S45), not
    # carpet area -- they differ by about 2.5x, so the wrong one here would
    # quietly report a rate that looks plausible and is not.
    s = compute(model, params, params["construction_area_sqft"])
    return {
        "sections": [{"id": x.id, "code": x.code, "name": x.name,
                      "amount": x.amount, "lines": x.lines,
                      "carried": x.carried, "is_carried": x.is_carried,
                      "excel_ref": x.excel_ref} for x in s.sections],
        "subtotal": s.subtotal,
        "uplifts": [{"code": u.code, "label": u.label, "rate": u.rate,
                     "amount": u.amount, "basis": u.basis} for u in s.uplifts],
        "before_tax": s.before_tax, "tax": s.tax, "total": s.total,
        "construction_area_sqft": s.construction_area_sqft,
        "rate_per_sqft": s.rate_per_sqft,
        "derivation": _derivation(s.derivation) if s.derivation else None,
    }
