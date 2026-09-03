"""The local app: one process serving the API and the UI.

Run it with ``make run``. There is nothing else to start -- no database server,
no build step, no second process for the frontend. The same command will run on
the Holsinger server later, behind whatever proxy sits in front of it.

The split that matters is inside the routes, not around them:

* **Write routes are thin.**  They change an input, save, and log. They contain
  no arithmetic at all.
* **Read routes never write.**  They ask the engine and return what it says.

That is the same rule the UI shows as white cells and grey cells, enforced one
layer down: there is no endpoint through which a derived value can be set.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from qs_engine.model import ProjectModel, RoomOpening
from qs_engine.params import ParameterSet

from . import crud, service
from .crud import CrudError
from .store import Store

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
DB_PATH = Path(os.environ.get("QS_DB", ROOT / "qs.db"))
WORKBOOK = ROOT / "data" / "workbooks" / "20240131 - AVS Budget R0 - Discussion.xlsx"


def build_stamp() -> dict[str, Any]:
    """The running commit, read from git once and remembered.

    Falls back to "unknown" outside a checkout rather than failing -- a missing
    stamp must never stop the app starting.
    """
    if getattr(build_stamp, "_cached", None) is None:
        import subprocess
        stamp = {"commit": "unknown", "committed_at": "", "branch": ""}
        try:
            out = subprocess.run(
                ["git", "-C", str(ROOT), "log", "-1", "--format=%h%n%cs%n%D"],
                capture_output=True, text=True, timeout=5, check=True).stdout
            commit, date, refs = (out.splitlines() + ["", "", ""])[:3]
            branch = ""
            for ref in refs.split(", "):
                if ref.startswith("HEAD -> "):
                    branch = ref[len("HEAD -> "):]
            stamp = {"commit": commit, "committed_at": date, "branch": branch}
        except Exception:
            pass
        build_stamp._cached = stamp
    return dict(build_stamp._cached)


class State:
    """The open project, held in memory and written through on every change.

    A QS edits one project at a time and the whole model is a few thousand rows,
    so keeping it in memory keeps every recalculation instant -- which is the
    point. Each write persists immediately, so nothing is lost on a crash.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.store = Store(db_path)
        self.project_id: str | None = None
        self.model: ProjectModel | None = None
        self.params: ParameterSet = ParameterSet.defaults()
        ids = self.store.project_ids()
        if ids:
            self.open(ids[0])

    def open(self, project_id: str) -> None:
        self.model = self.store.load(project_id)
        self.params = self.store.load_params(project_id)
        self.project_id = project_id

    def require(self) -> tuple[ProjectModel, ParameterSet]:
        if self.model is None:
            raise HTTPException(404, "no project loaded -- run `make seed` first")
        return self.model, self.params

    def persist(self) -> None:
        if self.model is not None:
            self.store.save(self.model, self.params)


state = State()
app = FastAPI(title="DBOT QS Platform", version="0.5.0", docs_url="/api/docs")


# --------------------------------------------------------------------------
# Read -- everything here is computed by the engine on request
# --------------------------------------------------------------------------

@app.get("/api/headline")
def get_headline() -> dict[str, Any]:
    model, params = state.require()
    return service.headline(model, params)


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    return {"projects": state.store.projects(), "open": state.project_id}


@app.get("/api/room-config")
def get_room_config() -> dict[str, Any]:
    model, _ = state.require()
    return service.room_config(model)


@app.get("/api/unit-types")
def get_unit_types() -> list[dict[str, Any]]:
    model, params = state.require()
    return service.unit_types(model, params)


@app.get("/api/unit-types/{unit_type_id}/rooms")
def get_unit_rooms(unit_type_id: str) -> dict[str, Any]:
    model, params = state.require()
    try:
        data = service.unit_rooms(model, params, unit_type_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    # Rates beside every quantity -- the thing the take-off makes possible.
    costs = service.room_costs(model, params, unit_type_id)
    for room in data["rooms"]:
        room["costs"] = costs.get(room["id"], [])
        room["amount"] = sum(c["total_amount"] for c in room["costs"])
    data["amount"] = sum(r["amount"] for r in data["rooms"])
    return data


@app.get("/api/openings")
def get_openings() -> dict[str, Any]:
    model, _ = state.require()
    return service.openings(model)


@app.get("/api/rates")
def get_rates() -> list[dict[str, Any]]:
    model, params = state.require()
    return service.rates(model, params)


@app.get("/api/parameters")
def get_parameters() -> list[dict[str, Any]]:
    _, params = state.require()
    return [{"key": p.key, "value": p.value, "unit": p.unit,
             "description": p.description, "source": p.source,
             "is_named": p.is_named} for p in params]


@app.get("/api/takeoff")
def get_takeoff(unit_type_id: str | None = None) -> dict[str, Any]:
    model, params = state.require()
    return service.takeoff(model, params, unit_type_id)


@app.get("/api/opening-totals")
def get_opening_totals() -> dict[str, Any]:
    model, params = state.require()
    return service.opening_costs(model, params)


@app.get("/api/finish-totals")
def get_finish_totals() -> dict[str, Any]:
    model, params = state.require()
    return service.finish_totals(model, params)


@app.get("/api/room-type-mapping")
def get_room_type_mapping() -> dict[str, Any]:
    model, _ = state.require()
    return {"mappings": service.room_type_mapping(model),
            "targets": service.priceable_room_types(model)}


@app.put("/api/room-type-mapping/{room_type_id}")
def set_room_type_mapping(room_type_id: str,
                          payload: dict = Body(...)) -> dict[str, Any]:
    """Point a room type at the rate block that prices it, or confirm the guess.

    Nothing here is applied silently: the importer proposed these links and each
    stays flagged until this endpoint records that somebody agreed.
    """
    model, _ = state.require()
    try:
        room_type = model.room_type(room_type_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc

    if "prices_as_id" in payload:
        target = payload["prices_as_id"] or None
        if target == room_type_id:
            target = None
        old = room_type.prices_as_id
        room_type.prices_as_id = target
        state.store.log(model.project.id, "room_type", room_type_id,
                        "prices_as_id", old, target)
    if "confirmed" in payload:
        room_type.mapping_confirmed = bool(payload["confirmed"])
        state.store.log(model.project.id, "room_type", room_type_id,
                        "mapping_confirmed", None, room_type.mapping_confirmed)
    return _touched()


@app.get("/api/reference")
def get_reference() -> dict[str, Any]:
    """Everything a dropdown needs.

    The UI never invents an option. Anywhere a value must come from a known set
    it is chosen from this list, which is why a misspelling cannot enter the
    model the way ``Vitrfied Skirting`` and ``Membrame`` entered the workbook
    and broke its lookups (C-34).
    """
    from qs_engine.model import (BuildupMethod, FloorType, OpeningKind,
                                 RoomCategory)
    model, _ = state.require()
    return {
        "room_types": [{"value": t.id, "label": t.name,
                        "category": t.category.value}
                       for t in sorted(model.room_types, key=lambda t: t.name)],
        "room_categories": [{"value": c.value, "label": c.value.title()}
                            for c in RoomCategory],
        "floor_types": [{"value": f.value, "label": f.value.title()}
                        for f in FloorType],
        "opening_kinds": [{"value": k.value, "label": k.value.replace("_", " ").title()}
                          for k in OpeningKind],
        "buildup_methods": [{"value": m.value,
                             "label": m.value.replace("_", " ")}
                            for m in BuildupMethod],
        "units": [{"value": u, "label": u} for u in
                  ("Sq M", "Sq Ft", "RM", "R Ft", "Cu M", "Nos", "Ton", "Kg", "LS")],
        "classifications": sorted({u.classification for u in model.unit_types
                                   if u.classification}),
        "unit_types": [{"value": u.id, "label": u.code}
                       for u in sorted(model.unit_types, key=lambda u: u.seq)],
        "opening_types": [{"value": o.id, "label": f"{o.code} ({o.kind.value})"}
                          for o in sorted(model.opening_types, key=lambda o: o.code)],
        "rate_items": [{"value": r.id,
                        "label": f"{r.description}"
                                 + (f" — {r.specification}" if r.specification else "")}
                       for r in sorted(model.rate_items, key=lambda r: r.description)],
        "finish_slots": [{"value": s.id, "label": s.name}
                         for s in sorted(model.finish_slots, key=lambda s: s.seq)],
    }


@app.get("/api/validation")
def get_validation() -> dict[str, Any]:
    model, params = state.require()
    return service.validation(model, params)


@app.get("/api/audit")
def get_audit() -> list[dict[str, Any]]:
    model, _ = state.require()
    return state.store.audit(model.project.id)


@app.get("/api/reconciliation")
def get_reconciliation() -> dict[str, Any]:
    """Excel versus platform, line by line.

    Reads the workbook fresh rather than the database, because the point is to
    compare the platform against the source of truth, not against itself.
    """
    if not WORKBOOK.exists():
        raise HTTPException(404, f"workbook not found at {WORKBOOK}")
    from qs_importer.pipeline import import_workbook
    from qs_importer.reconcile import build_lines

    result = import_workbook(WORKBOOK)
    lines = build_lines(result)
    return {
        "workbook": WORKBOOK.name,
        "lines": [
            {"section": l.section, "label": l.label, "excel": l.excel,
             "platform": l.platform, "difference": l.difference,
             "status": l.status.value, "excel_ref": l.excel_ref,
             "explanation": l.explanation}
            for l in lines
        ],
        "pass": sum(1 for l in lines if l.status.value == "PASS"),
        "explained": sum(1 for l in lines if l.status.value == "EXPLAINED"),
        "fail": sum(1 for l in lines if l.status.value == "FAIL"),
        "warnings": result.warnings,
    }


# --------------------------------------------------------------------------
# Write -- inputs only. No arithmetic lives in any of these.
# --------------------------------------------------------------------------

def _touched() -> dict[str, Any]:
    """Persist and hand back the recomputed headline.

    Every write returns fresh totals, so the UI never has to work out what a
    change should have done -- it just renders what the engine now says.
    """
    state.persist()
    model, params = state.require()
    return {"ok": True, "headline": service.headline(model, params)}


@app.put("/api/room-config/cell")
def set_mix(payload: dict = Body(...)) -> dict[str, Any]:
    """One cell of the floor x unit-type matrix."""
    model, _ = state.require()
    floor_id = payload["floor_id"]
    unit_type_id = payload["unit_type_id"]
    count = int(payload.get("count") or 0)

    existing = next((m for m in model.floor_unit_mix
                     if m.floor_id == floor_id and m.unit_type_id == unit_type_id), None)
    old = existing.count if existing else 0
    if count <= 0:
        if existing:
            model.floor_unit_mix.remove(existing)
    elif existing:
        existing.count = count
    else:
        from qs_engine.model import FloorUnitMix
        model.floor_unit_mix.append(FloorUnitMix(
            id=f"{floor_id}--{unit_type_id}", floor_id=floor_id,
            unit_type_id=unit_type_id, count=count))
    state.store.log(model.project.id, "floor_unit_mix",
                    f"{floor_id}/{unit_type_id}", "count", old, count)
    return _touched()


@app.put("/api/floors/{floor_id}")
def set_floor(floor_id: str, payload: dict = Body(...)) -> dict[str, Any]:
    """A floor's height. Every wall quantity on that floor follows it."""
    model, _ = state.require()
    try:
        floor = model.floor(floor_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    for field in ("name", "floor_to_floor_ht"):
        if field in payload:
            old = getattr(floor, field)
            setattr(floor, field, payload[field])
            state.store.log(model.project.id, "floor", floor_id, field,
                            old, payload[field])
    return _touched()


ROOM_FIELDS = {"label", "count_per_unit", "carpet_area_sqm", "perimeter_m",
               "clear_height_m", "dado_height_m"}


@app.put("/api/rooms/{room_id}")
def set_room(room_id: str, payload: dict = Body(...)) -> dict[str, Any]:
    """A room's dimensions. Note what is absent: no area in square feet.

    ``area_sqft`` is derived and has no field, no column and no endpoint, which
    is what makes the ``Flat Sizes!E57`` paste -- a perimeter typed into an area
    column -- impossible rather than merely detectable (C-3).
    """
    model, _ = state.require()
    try:
        room = model.room(room_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    for field, value in payload.items():
        if field not in ROOM_FIELDS:
            raise HTTPException(
                400, f"{field!r} is not an input. Derived values cannot be set.")
        old = getattr(room, field)
        setattr(room, field, value)
        state.store.log(model.project.id, "unit_type_room", room_id, field, old, value)
    return _touched()


RATE_FIELDS = {"basic_rate", "laying_rate", "wastage_pct", "frame_width_m"}


@app.put("/api/rates/{rate_item_id}")
def set_rate(rate_item_id: str, payload: dict = Body(...)) -> dict[str, Any]:
    """A rate's components. The overall rate is computed, never set."""
    model, _ = state.require()
    revision = model.current_revision(rate_item_id)
    if revision is None:
        raise HTTPException(404, f"no rate revision for {rate_item_id!r}")
    for field, value in payload.items():
        if field not in RATE_FIELDS:
            raise HTTPException(
                400, f"{field!r} is not an input. The overall rate is derived "
                     f"from basic rate, laying rate and wastage.")
        old = getattr(revision, field)
        setattr(revision, field, value)
        state.store.log(model.project.id, "rate_revision", revision.id,
                        field, old, value)
    return _touched()


@app.put("/api/opening-types/{opening_type_id}")
def set_opening_type(opening_type_id: str, payload: dict = Body(...)) -> dict[str, Any]:
    model, _ = state.require()
    try:
        opening = model.opening_type(opening_type_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    for field in ("width_m", "height_m", "specification"):
        if field in payload:
            old = getattr(opening, field)
            setattr(opening, field, payload[field])
            state.store.log(model.project.id, "opening_type", opening_type_id,
                            field, old, payload[field])
    return _touched()


@app.put("/api/room-openings/{room_opening_id}")
def set_room_opening(room_opening_id: str, payload: dict = Body(...)) -> dict[str, Any]:
    """How many of an opening a room has. Changes every deduction that uses it."""
    model, _ = state.require()
    opening = next((o for o in model.room_openings if o.id == room_opening_id), None)
    if opening is None:
        raise HTTPException(404, f"no room opening {room_opening_id!r}")
    count = float(payload.get("count") or 0)
    old = opening.count
    if count <= 0:
        model.room_openings.remove(opening)
    else:
        opening.count = count
    state.store.log(model.project.id, "room_opening", room_opening_id,
                    "count", old, count)
    return _touched()


@app.post("/api/rooms/{room_id}/openings")
def add_room_opening(room_id: str, payload: dict = Body(...)) -> dict[str, Any]:
    """Add an opening to a room -- and watch the deductions move by themselves."""
    model, _ = state.require()
    opening_type_id = payload["opening_type_id"]
    count = float(payload.get("count") or 1)
    new_id = f"{room_id}--{opening_type_id}--{len(model.room_openings)}"
    model.room_openings.append(RoomOpening(
        id=new_id, unit_type_room_id=room_id,
        opening_type_id=opening_type_id, count=count))
    state.store.log(model.project.id, "room_opening", new_id, "count", None, count)
    return _touched()


@app.put("/api/parameters/{key}")
def set_parameter(key: str, payload: dict = Body(...)) -> dict[str, Any]:
    """Change a named parameter and every rate built on it moves at once."""
    model, params = state.require()
    try:
        old = params[key]
        state.params = params.with_value(key, float(payload["value"]),
                                         reason=payload.get("reason", ""))
    except KeyError as exc:
        raise HTTPException(404, f"unknown parameter {key!r}") from exc
    state.store.save_params(model.project.id, state.params)
    state.store.log(model.project.id, "project_parameter", key, "value",
                    old, payload["value"], reason=payload.get("reason", ""))
    return _touched()


# --------------------------------------------------------------------------
# Add, rename and delete -- one pair of routes for every collection
# --------------------------------------------------------------------------

@app.get("/api/collections")
def list_collections() -> dict[str, Any]:
    """What can be added, and which of its fields are inputs.

    The UI reads this to build its forms, so a field that is not an input here
    cannot be offered for editing there.
    """
    return {
        name: {"label": spec.label, "required": list(spec.required),
               "editable": list(spec.editable)}
        for name, spec in crud.RESOURCES.items()
    }


@app.post("/api/collections/{name}")
def create_record(name: str, payload: dict = Body(default={})) -> dict[str, Any]:
    model, _ = state.require()
    try:
        item = crud.create(model, name, payload)
    except CrudError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    state.store.log(model.project.id, name, item.id, "created", None,
                    getattr(item, "code", None) or getattr(item, "name", None)
                    or getattr(item, "label", None) or item.id)
    return {**_touched(), "id": item.id}


@app.patch("/api/collections/{name}/{entity_id}")
def update_record(name: str, entity_id: str,
                  payload: dict = Body(...)) -> dict[str, Any]:
    """Rename or re-point a record. Derived fields are refused."""
    model, _ = state.require()
    try:
        changes = crud.update(model, name, entity_id, payload)
    except CrudError as exc:
        raise HTTPException(400, str(exc)) from exc
    for field, old, new in changes:
        state.store.log(model.project.id, name, entity_id, field, old, new)
    return _touched()


@app.get("/api/collections/{name}/{entity_id}/usage")
def record_usage(name: str, entity_id: str) -> dict[str, Any]:
    """What would refuse a delete -- so the UI can warn before asking."""
    model, _ = state.require()
    try:
        return {"blocked_by": crud.blockers(model, name, entity_id)}
    except CrudError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/collections/{name}/{entity_id}")
def delete_record(name: str, entity_id: str) -> dict[str, Any]:
    """Delete a record, taking its own children but never a record in use."""
    model, _ = state.require()
    try:
        removed = crud.delete(model, name, entity_id)
    except CrudError as exc:
        raise HTTPException(409, str(exc)) from exc
    state.store.log(model.project.id, name, entity_id, "deleted",
                    ", ".join(f"{n} {k}" for k, n in removed.items()), None)
    return {**_touched(), "removed": removed}


# --------------------------------------------------------------------------
# The UI, served by the same process
# --------------------------------------------------------------------------

@app.get("/api/derivation/health")
def health() -> dict[str, Any]:
    return {"ok": True, "project": state.project_id, "db": str(state.store.path)}


@app.get("/api/version")
def version() -> dict[str, Any]:
    """Which build is actually running.

    Without this, "did my pull take effect?" can only be answered by reading
    source. The UI puts the commit in the header so it is one glance.
    """
    return build_stamp()


#: Served on every UI response.
#:
#: Starlette sends ``etag`` and ``last-modified`` but never ``Cache-Control``,
#: and the module URLs carry no version. With no ``Cache-Control`` a browser
#: falls back to heuristic freshness -- roughly a tenth of the file's age -- and
#: reuses ``app.js`` for hours without asking. Pull a new build and the screen
#: does not change: a route added to the new ``app.js`` is never registered, so
#: the router falls through and the page comes up empty.
#:
#: This is one process a QS runs on their own machine. There is nothing to gain
#: from caching it and a whole class of "I pulled and nothing happened" to lose.
NO_STORE = "no-store, no-cache, must-revalidate, max-age=0"


class NoStoreStatic(StaticFiles):
    """Static files that a reload always re-fetches."""

    def file_response(self, *args: Any, **kwargs: Any):  # noqa: ANN201
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = NO_STORE
        return response


def _page(path: Path) -> FileResponse:
    return FileResponse(path, headers={"Cache-Control": NO_STORE})


if WEB.exists():
    app.mount("/static", NoStoreStatic(directory=WEB), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return _page(WEB / "index.html")


@app.exception_handler(404)
def not_found(request, exc):  # noqa: ANN001
    if request.url.path.startswith("/api"):
        return JSONResponse({"error": str(exc.detail)}, status_code=404)
    return _page(WEB / "index.html")
