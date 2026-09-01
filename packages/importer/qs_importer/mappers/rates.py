"""Rate List - Flats / - Office -> rate items, revisions and the finish schedule.

The sheet is a block per room type, each block the same eleven finish slots:
Flooring, Skirting, Dado, Wall plaster, Ceiling plaster, False ceiling, Wall
paint, Ceiling paint, Door frames, Window frames (internal and external),
Others.  That structure *is* the finish schedule, and it generalises: a toilet
block prices Dado and a bedroom block leaves it blank, which is exactly
``room_finish_spec.is_applicable``.

Two things get fixed in the crossing.

**The overall rate becomes a computation, not a formula.**  Column G mixes four
constants into its text, and the wastage among them is not one number -- 1.1 for
flooring, 1.15 for toilet dado (``G64``), 1.05 for back-coat plaster (``G263``),
1.03 on reinforcement steel (``G245``).  Reading them out per row is what makes
wastage an editable field instead of a digit buried in a formula.

**Rates get an identity.**  In the workbook a take-off line reaches its rate by
row offset, and rates propagate between blocks by a daisy chain of cell
references mixing relative and absolute anchors -- ``E20 = E6``, ``E34 = E20``,
but ``E23 = $E$9`` (C-32).  Break one link and some rooms follow a change while
others silently do not.  Here identical rates collapse to one ``rate_item`` that
every room referencing it shares.
"""

from __future__ import annotations

import re

from qs_engine.model import (BuildupMethod, FinishSlot, ProjectModel, RateItem,
                             RateRevision, RoomFinishSpec, RoomType)

from ..ids import IdFactory
from ..reader import Workbook
from .unit_sizes import categorise

SHEET_FLATS = "Rate List - Flats"
SHEET_OFFICE = "Rate List - Office"

COL_MARKER, COL_ITEM, COL_SPEC = "A", "B", "C"
COL_UNIT_IN, COL_BASIC, COL_LAYING, COL_OVERALL, COL_UNIT_OUT = "D", "E", "F", "G", "H"

_ROOM_BLOCK_MARKER = "#"

_NUM = r"\d+(?:\.\d+)?"


def _norm(formula: str) -> str:
    return re.sub(r"\s+", "", formula or "").lstrip("=").lstrip("+")


def classify_formula(formula: str | None, cached: float | None) -> tuple[
        BuildupMethod, float | None, float, float, float | None]:
    """Read a build-up method, wastage, factor and constant out of column G.

    Returns ``(method, wastage_pct_or_None, adjustment_factor,
    adjustment_constant, frame_width_or_None)``.  Everything the formula encodes
    becomes a named field; nothing is left as an unexplained digit.
    """
    if not formula:
        return (BuildupMethod.CONSTANT, None, 1.0, 0.0, None)
    f = _norm(formula)

    # (E*w + F) * 10.764  -- flooring, and the G232 variant written as
    # (E*10.764*w + F*10.764), which is the same thing rearranged.
    m = re.fullmatch(rf"\(?E{_NUM}\*({_NUM})\+F{_NUM}\)?\*({_NUM})", f) \
        or re.fullmatch(rf"\(E{_NUM}\*({_NUM})\+F{_NUM}\)\*({_NUM})", f)
    if m:
        wastage, factor = float(m.group(1)) - 1.0, float(m.group(2))
        method = (BuildupMethod.LINEAR_WITH_WASTAGE if factor < 5
                  else BuildupMethod.AREA_WITH_WASTAGE)
        return (method, wastage, 1.0, 0.0, None)

    m = re.fullmatch(rf"\(E{_NUM}\*({_NUM})\*({_NUM})\+F{_NUM}\*({_NUM})\)", f)
    if m:
        return (BuildupMethod.AREA_WITH_WASTAGE, float(m.group(2)) - 1.0, 1.0, 0.0, None)

    # E * 10.764 -- plaster and paint, no wastage (Q-6)
    m = re.fullmatch(rf"E{_NUM}\*({_NUM})", f)
    if m:
        return (BuildupMethod.AREA_SIMPLE, 0.0, 1.0, 0.0, None)

    # (E * (0.1 * 1 * 1.1 * 10.764)) + (F * 3.28) -- frames
    # (E * (width * [1 *] wastage * 10.764)) + (F * 3.28).  Width is normally
    # 0.1 but G102 uses 2.2, so it is read out rather than assumed.
    m = re.fullmatch(
        rf"\(E{_NUM}\*\(({_NUM})\*(?:{_NUM}\*)?({_NUM})\*{_NUM}\)\)\+\(F{_NUM}\*{_NUM}\)", f)
    if m:
        return (BuildupMethod.FRAME, float(m.group(2)) - 1.0, 1.0, 0.0,
                float(m.group(1)))

    # (E + F) * 10.764, optionally with a trailing factor or rebate
    m = re.fullmatch(rf"\(E{_NUM}\+F{_NUM}\)\*({_NUM})", f)
    if m:
        factor = float(m.group(1))
        if factor > 5:
            return (BuildupMethod.AREA_SUM, None, 1.0, 0.0, None)
        return (BuildupMethod.PASSTHROUGH, None, factor, 0.0, None)

    m = re.fullmatch(rf"\(E{_NUM}\+F{_NUM}\)-({_NUM})", f)
    if m:
        return (BuildupMethod.PASSTHROUGH, None, 1.0, -float(m.group(1)), None)

    if re.fullmatch(rf"E{_NUM}\+F{_NUM}", f):
        return (BuildupMethod.PASSTHROUGH, None, 1.0, 0.0, None)
    if re.fullmatch(rf"E{_NUM}", f) or re.fullmatch(rf"F{_NUM}", f):
        return (BuildupMethod.PASSTHROUGH, None, 1.0, 0.0, None)
    if re.fullmatch(rf"G{_NUM}", f):
        return (BuildupMethod.LINK, None, 1.0, 0.0, None)
    if re.fullmatch(rf"\$?G\$?{_NUM}", f):
        return (BuildupMethod.LINK, None, 1.0, 0.0, None)
    return (BuildupMethod.CONSTANT, None, 1.0, 0.0, None)


def _slot_code(item: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", " ".join(str(item).split()).lower()).strip("_")


def map_rate_list(wb: Workbook, model: ProjectModel, ids: IdFactory,
                  sheet: str = SHEET_FLATS, first_row: int = 4,
                  last_row: int = 300) -> list[str]:
    """Read one rate list into rate items, revisions and finish specs."""
    warnings: list[str] = []
    slots: dict[str, FinishSlot] = {s.code: s for s in model.finish_slots}
    room_types = {rt.name.strip().lower(): rt for rt in model.room_types}
    # Identical (item, spec, basic, laying) collapse to one rate item.
    by_signature: dict[tuple, RateItem] = {}
    current_room: RoomType | None = None
    # Row -> rate item, so ``=G168`` can be resolved to an identity in a second
    # pass. Until it is, a LINK is just another cell reference.
    item_by_row: dict[int, str] = {}
    pending_links: list[tuple[RateRevision, int, float | None, str]] = []

    for row in range(first_row, last_row + 1):
        marker = wb.text(sheet, f"{COL_MARKER}{row}")
        item = wb.text(sheet, f"{COL_ITEM}{row}")
        if not item:
            continue

        if marker and marker != _ROOM_BLOCK_MARKER:
            # A section marker ("A" Internal Finishes, "B" Civil Works...).
            # Without this reset, the Civil Works rows at the foot of the sheet
            # would attach as finishes of whichever room block came last.
            current_room = None
            continue

        if marker == _ROOM_BLOCK_MARKER:
            key = " ".join(item.split()).lower()
            current_room = room_types.get(key)
            if current_room is None:
                current_room = RoomType(
                    id=ids.make(model.project.id, "rt", item),
                    project_id=model.project.id,
                    name=" ".join(item.split()), category=categorise(item))
                model.room_types.append(current_room)
                room_types[key] = current_room
                warnings.append(
                    f"{sheet}!{COL_ITEM}{row}: rate block {item!r} names a room "
                    f"type that is not in the sizes sheet. The rate list and the "
                    f"sizes sheet use different room vocabularies, so a finish "
                    f"can be priced for a room that does not exist."
                )
            continue

        basic = wb.number(sheet, f"{COL_BASIC}{row}")
        laying = wb.number(sheet, f"{COL_LAYING}{row}")
        overall = wb.number(sheet, f"{COL_OVERALL}{row}")
        formula = wb.formula(sheet, f"{COL_OVERALL}{row}")
        if basic is None and laying is None and overall is None:
            continue  # a slot that exists but is not priced for this room

        method, wastage, factor, constant, frame_w = classify_formula(formula, overall)
        spec = wb.text(sheet, f"{COL_SPEC}{row}")
        unit_out = wb.text(sheet, f"{COL_UNIT_OUT}{row}") or "Sq M"

        signature = (" ".join(item.split()).lower(), spec.lower(), basic, laying,
                     method, wastage, factor, constant, frame_w, overall if method is
                     BuildupMethod.CONSTANT else None)
        rate_item = by_signature.get(signature)
        if rate_item is None:
            rate_item = RateItem(
                id=ids.make(model.project.id, "rate", item, spec or row),
                project_id=model.project.id,
                code=_slot_code(item).upper()[:24],
                description=" ".join(item.split()),
                unit=unit_out, specification=spec,
                category="Finishing" if current_room else "Works",
            )
            model.rate_items.append(rate_item)
            model.rate_revisions.append(RateRevision(
                id=ids.make(rate_item.id, "rev1"),
                rate_item_id=rate_item.id, method=method,
                basic_rate=basic, laying_rate=laying, wastage_pct=wastage,
                adjustment_factor=factor, adjustment_constant=constant,
                frame_width_m=frame_w,
                constant_value=overall if method is BuildupMethod.CONSTANT else None,
                revision_no=1, source=f"{sheet}!{COL_OVERALL}{row}",
            ))
            by_signature[signature] = rate_item
        item_by_row[row] = rate_item.id
        if method is BuildupMethod.LINK:
            target_row = int(re.sub(r"[^0-9]", "", _norm(formula)))
            pending_links.append(
                (model.rate_revisions[-1], target_row, overall,
                 f"{sheet}!{COL_OVERALL}{row}"))

        if current_room is None:
            continue
        code = _slot_code(item)
        slot = slots.get(code)
        if slot is None:
            slot = FinishSlot(id=ids.make("slot", code), code=code,
                              name=" ".join(item.split()), unit=unit_out,
                              qty_rule=_DEFAULT_QTY_RULE.get(code, ""),
                              seq=len(slots))
            model.finish_slots.append(slot)
            slots[code] = slot
        model.room_finish_specs.append(RoomFinishSpec(
            id=ids.make(current_room.id, slot.id),
            project_id=model.project.id, room_type_id=current_room.id,
            finish_slot_id=slot.id, rate_item_id=rate_item.id,
            qty_rule=slot.qty_rule or None, is_applicable=True,
            notes=f"from {sheet}!{COL_ITEM}{row}",
        ))

    _resolve_links(pending_links, item_by_row, warnings)
    return warnings


def _resolve_links(pending, item_by_row: dict[int, str],
                   warnings: list[str]) -> None:
    """Turn ``=G168`` into a reference to the rate item that row produced.

    A link that cannot be resolved becomes a constant carrying the value the
    workbook last computed, so no money moves -- and a warning, because a rate
    that mirrors nothing is a rate nobody can maintain.
    """
    for revision, target_row, cached, source in pending:
        target = item_by_row.get(target_row)
        if target and target != revision.rate_item_id:
            revision.links_to_rate_item_id = target
            continue
        revision.method = BuildupMethod.CONSTANT
        revision.constant_value = cached
        warnings.append(
            f"{source}: mirrors row {target_row}, which produced no rate item. "
            f"Frozen at its last computed value ({cached}). In the workbook "
            f"rates propagate by a daisy chain of such references (C-32); break "
            f"one and some rooms follow a change while others do not."
        )


#: Which quantity rule each finish slot uses.  Written once here instead of
#: 1,451 times in the take-off.
_DEFAULT_QTY_RULE: dict[str, str] = {
    "flooring": "floor_area",
    "skirting": "skirting",
    "dado": "dado",
    "wall_finishes_plaster": "wall_finish",
    "ceiling_plaster": "ceiling_area",
    "false_ceiling": "ceiling_area",
    "wall_finishes_paint": "wall_finish",
    "ceiling_paint": "ceiling_area",
    "door_frames": "door_frame",
    "window_frames_internal": "window_frame",
    "window_frames_external": "window_frame",
}
