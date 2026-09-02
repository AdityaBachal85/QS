"""Adding, renaming and deleting the things a project is made of.

Every screen so far could only edit values in cells that already existed. That
is enough to check an imported project and useless for building a new one: you
could not add a floor, add a fourth toilet, rename a flat type, or add a rate.
This module is what makes the platform usable without a spreadsheet beside it.

Two rules govern deletion, and both come from defects in the source workbook:

* **A container takes its own children with it.**  Deleting a unit type removes
  its rooms and their openings, because those rows mean nothing without it.
* **A shared master in use is never deleted.**  Deleting a room type that rooms
  still reference, or a rate an item is still priced on, is refused, and the
  message names what uses it.  The workbook carries eight live ``#REF!`` errors
  from exactly this (C-10) -- a deletion that broke references and nobody saw.

Deleting never renumbers anything else.  ``seq`` orders rows; it is an
attribute, not a position, so removing floor 12 leaves floor 13 as floor 13.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field, fields
from typing import Any, Callable

from qs_engine import model as M


class CrudError(Exception):
    """A create or delete that must not proceed, with a reason a QS can read."""


def slug(*parts: object) -> str:
    text = " ".join(str(p) for p in parts if p not in (None, ""))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "item"


def new_id(model: M.ProjectModel, *parts: object) -> str:
    """A readable id that is unique within the project.

    Readable so a failing test names the thing that failed; unique so nothing
    ever collides with a row imported from the workbook.
    """
    used = {
        item.id
        for _, spec in RESOURCES.items()
        for item in getattr(model, spec.attr, [])
    }
    base = slug(*parts)
    if base not in used:
        return base
    return f"{base}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class Link:
    """A reference from one collection to another."""

    resource: str
    field: str
    label: str


@dataclass(frozen=True)
class Resource:
    name: str
    cls: type
    attr: str
    label: str
    #: Fields the caller must supply. Everything else has a sensible default.
    required: tuple[str, ...] = ()
    #: Builds the id and fills in defaults from the payload and the model.
    prepare: Callable[[M.ProjectModel, dict], dict] | None = None
    #: Children removed along with this record.
    cascade: tuple[Link, ...] = ()
    #: References that refuse the delete while they exist.
    blocks: tuple[Link, ...] = ()
    #: Fields editable through the generic update path.
    editable: tuple[str, ...] = ()


def _next_seq(items, attr: str = "seq") -> int:
    return max((getattr(i, attr, 0) or 0 for i in items), default=0) + 1


def _prepare_floor(model: M.ProjectModel, payload: dict) -> dict:
    if not model.buildings:
        raise CrudError("this project has no building yet")
    name = payload.get("name") or f"Floor {_next_seq(model.floors)}"
    return {
        "id": new_id(model, "floor", name),
        "building_id": payload.get("building_id") or model.buildings[0].id,
        "seq": int(payload.get("seq") or _next_seq(model.floors)),
        "name": name,
        "floor_to_floor_ht": float(payload.get("floor_to_floor_ht") or 3.0),
        "floor_type": M.FloorType(payload.get("floor_type") or "typical"),
    }


def _prepare_unit_type(model: M.ProjectModel, payload: dict) -> dict:
    code = payload.get("code") or f"Type {_next_seq(model.unit_types)}"
    classification = payload.get("classification") or "Unassigned"
    return {
        "id": new_id(model, "ut", code),
        "project_id": model.project.id,
        "code": code,
        "classification": classification,
        "is_residential": bool(payload.get("is_residential", True)),
        "is_common_area": bool(payload.get("is_common_area", False)),
        "seq": int(payload.get("seq") or _next_seq(model.unit_types)),
    }


def _prepare_room_type(model: M.ProjectModel, payload: dict) -> dict:
    name = payload.get("name") or "New room type"
    return {
        "id": new_id(model, "rt", name),
        "project_id": model.project.id,
        "name": name,
        "category": M.RoomCategory(payload.get("category") or "habitable"),
    }


def _prepare_room(model: M.ProjectModel, payload: dict) -> dict:
    """A room is added to a unit type; four toilets is simply four of these."""
    unit_type_id = payload.get("unit_type_id")
    if not unit_type_id:
        raise CrudError("a room needs a unit type")
    model.unit_type(unit_type_id)
    room_type_id = payload.get("room_type_id") or (
        model.room_types[0].id if model.room_types else None)
    if not room_type_id:
        raise CrudError("define a room type first")
    room_type = model.room_type(room_type_id)
    label = payload.get("label") or room_type.name
    return {
        "id": new_id(model, unit_type_id, "room", label),
        "unit_type_id": unit_type_id,
        "room_type_id": room_type_id,
        "seq": int(payload.get("seq") or _next_seq(model.rooms_of(unit_type_id))),
        "label": label,
        "count_per_unit": float(payload.get("count_per_unit") or 1),
        "carpet_area_sqm": float(payload.get("carpet_area_sqm") or 0),
        "perimeter_m": float(payload.get("perimeter_m") or 0),
    }


def _prepare_opening_type(model: M.ProjectModel, payload: dict) -> dict:
    code = payload.get("code") or f"OP{_next_seq(model.opening_types, 'width_m')}"
    return {
        "id": new_id(model, "op", code),
        "project_id": model.project.id,
        "code": code,
        "kind": M.OpeningKind(payload.get("kind") or "door"),
        "width_m": float(payload.get("width_m") or 0),
        "height_m": float(payload.get("height_m") or 0),
        "specification": payload.get("specification") or "",
    }


def _prepare_room_opening(model: M.ProjectModel, payload: dict) -> dict:
    room_id = payload.get("unit_type_room_id")
    opening_type_id = payload.get("opening_type_id")
    if not room_id or not opening_type_id:
        raise CrudError("an opening needs a room and an opening type")
    model.room(room_id)
    model.opening_type(opening_type_id)
    return {
        "id": new_id(model, room_id, opening_type_id),
        "unit_type_room_id": room_id,
        "opening_type_id": opening_type_id,
        "count": float(payload.get("count") or 1),
    }


def _prepare_rate_item(model: M.ProjectModel, payload: dict) -> dict:
    description = payload.get("description") or "New rate"
    return {
        "id": new_id(model, "rate", description, payload.get("specification") or ""),
        "project_id": model.project.id,
        "code": slug(description).upper()[:24],
        "description": description,
        "unit": payload.get("unit") or "Sq M",
        "category": payload.get("category") or "Finishing",
        "specification": payload.get("specification") or "",
    }


RESOURCES: dict[str, Resource] = {
    "floors": Resource(
        "floors", M.Floor, "floors", "floor",
        required=(), prepare=_prepare_floor,
        cascade=(Link("floor_unit_mix", "floor_id", "unit mix rows"),),
        editable=("name", "seq", "floor_to_floor_ht", "floor_type"),
    ),
    "unit-types": Resource(
        "unit-types", M.UnitType, "unit_types", "unit type",
        prepare=_prepare_unit_type,
        cascade=(Link("floor_unit_mix", "unit_type_id", "unit mix rows"),
                 Link("rooms", "unit_type_id", "rooms")),
        editable=("code", "classification", "is_residential", "is_common_area",
                  "seq", "count_override"),
    ),
    "room-types": Resource(
        "room-types", M.RoomType, "room_types", "room type",
        prepare=_prepare_room_type,
        cascade=(Link("finish-specs", "room_type_id", "finish schedule rows"),),
        blocks=(Link("rooms", "room_type_id", "rooms"),),
        editable=("name", "category"),
    ),
    "rooms": Resource(
        "rooms", M.UnitTypeRoom, "unit_type_rooms", "room",
        required=("unit_type_id",), prepare=_prepare_room,
        cascade=(Link("room-openings", "unit_type_room_id", "openings"),),
        editable=("label", "room_type_id", "seq", "count_per_unit",
                  "carpet_area_sqm", "perimeter_m", "clear_height_m",
                  "dado_height_m"),
    ),
    "opening-types": Resource(
        "opening-types", M.OpeningType, "opening_types", "opening type",
        prepare=_prepare_opening_type,
        blocks=(Link("room-openings", "opening_type_id", "openings in rooms"),),
        editable=("code", "kind", "width_m", "height_m", "specification",
                  "rate_item_id"),
    ),
    "room-openings": Resource(
        "room-openings", M.RoomOpening, "room_openings", "opening",
        required=("unit_type_room_id", "opening_type_id"),
        prepare=_prepare_room_opening,
        editable=("count", "linear_qty_m"),
    ),
    "rate-items": Resource(
        "rate-items", M.RateItem, "rate_items", "rate",
        prepare=_prepare_rate_item,
        cascade=(Link("rate-revisions", "rate_item_id", "revisions"),),
        blocks=(Link("finish-specs", "rate_item_id", "finish schedule rows"),
                Link("opening-types", "rate_item_id", "opening types")),
        editable=("description", "specification", "unit", "category", "is_active"),
    ),
    "rate-revisions": Resource(
        "rate-revisions", M.RateRevision, "rate_revisions", "rate revision",
        required=("rate_item_id",),
        editable=("method", "basic_rate", "laying_rate", "wastage_pct",
                  "frame_width_m", "adjustment_factor", "adjustment_constant",
                  "constant_value", "links_to_rate_item_id"),
    ),
    "finish-specs": Resource(
        "finish-specs", M.RoomFinishSpec, "room_finish_specs", "finish schedule row",
        required=("room_type_id", "finish_slot_id"),
        editable=("rate_item_id", "qty_rule", "is_applicable", "notes"),
    ),
    "floor_unit_mix": Resource(
        "floor_unit_mix", M.FloorUnitMix, "floor_unit_mix", "unit mix row",
        required=("floor_id", "unit_type_id"),
        editable=("count",),
    ),
}


def resource(name: str) -> Resource:
    spec = RESOURCES.get(name)
    if spec is None:
        raise CrudError(f"unknown collection {name!r}")
    return spec


def find(model: M.ProjectModel, name: str, entity_id: str):
    for item in getattr(model, resource(name).attr):
        if item.id == entity_id:
            return item
    raise CrudError(f"no {resource(name).label} with id {entity_id!r}")


def create(model: M.ProjectModel, name: str, payload: dict) -> Any:
    """Add one record, filling in defaults so a new row is immediately usable."""
    spec = resource(name)
    for required in spec.required:
        if not payload.get(required):
            raise CrudError(f"a {spec.label} needs {required}")

    if spec.prepare is not None:
        values = spec.prepare(model, payload)
    else:
        allowed = {f.name for f in fields(spec.cls)}
        values = {k: v for k, v in payload.items() if k in allowed}
        values.setdefault("id", new_id(model, name, payload.get("code")
                                       or payload.get("name") or "row"))
    item = spec.cls(**values)
    getattr(model, spec.attr).append(item)
    return item


def blockers(model: M.ProjectModel, name: str, entity_id: str) -> list[str]:
    """What refuses this delete, described in words rather than in ids."""
    found: list[str] = []
    for link in resource(name).blocks:
        child_spec = resource(link.resource)
        count = sum(1 for c in getattr(model, child_spec.attr)
                    if getattr(c, link.field, None) == entity_id)
        if count:
            found.append(f"{count} {link.label}")
    return found


def delete(model: M.ProjectModel, name: str, entity_id: str) -> dict[str, int]:
    """Remove one record, with its own children, or refuse and say why."""
    spec = resource(name)
    item = find(model, name, entity_id)

    held_by = blockers(model, name, entity_id)
    if held_by:
        raise CrudError(
            f"cannot delete this {spec.label}: it is used by "
            + ", ".join(held_by)
            + ". Reassign them first, so nothing is left pointing at a record "
              "that no longer exists."
        )

    removed: dict[str, int] = {}
    for link in spec.cascade:
        child_spec = resource(link.resource)
        children = [c for c in getattr(model, child_spec.attr)
                    if getattr(c, link.field, None) == entity_id]
        for child in children:
            # Recurse, so a unit type takes its rooms and those rooms take
            # their openings. The recursion reports each record it removed, so
            # nothing is counted twice here.
            for key, n in delete(model, link.resource, child.id).items():
                removed[key] = removed.get(key, 0) + n

    getattr(model, spec.attr).remove(item)
    removed[spec.label] = removed.get(spec.label, 0) + 1
    return removed


def update(model: M.ProjectModel, name: str, entity_id: str,
           payload: dict) -> list[tuple[str, Any, Any]]:
    """Change editable fields, refusing anything derived. Returns the changes."""
    spec = resource(name)
    item = find(model, name, entity_id)
    changes: list[tuple[str, Any, Any]] = []

    for key, value in payload.items():
        if key not in spec.editable:
            raise CrudError(
                f"{key!r} is not an input on a {spec.label}. Derived values are "
                f"computed and cannot be set."
            )
        old = getattr(item, key)
        annotation = {f.name: f.type for f in fields(spec.cls)}[key]
        setattr(item, key, _coerce(value, annotation, old))
        changes.append((key, old, getattr(item, key)))
    return changes


def _coerce(value: Any, annotation: Any, old: Any) -> Any:
    """Bring a JSON value to the type the field already holds."""
    if value is None:
        return None
    for enum_cls in (M.FloorType, M.RoomCategory, M.OpeningKind, M.BuildupMethod):
        if isinstance(old, enum_cls):
            return enum_cls(value)
        if isinstance(annotation, str) and annotation.startswith(enum_cls.__name__):
            return enum_cls(value)
    if isinstance(old, bool):
        return bool(value)
    if isinstance(old, int) and not isinstance(old, bool):
        return int(value)
    if isinstance(old, float):
        return float(value)
    if isinstance(old, str):
        return str(value)
    return value
