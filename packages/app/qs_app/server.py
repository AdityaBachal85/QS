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

from fastapi import (Body, Cookie, Depends, FastAPI, HTTPException,
                     Response)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from qs_engine.model import ProjectModel, RoomOpening
from qs_engine.params import ParameterSet

from . import auth, crud, service
from .auth import Role, User
from .crud import CrudError
from .store import Store, current_actor

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
DB_PATH = Path(os.environ.get("QS_DB", ROOT / "qs.db"))
WORKBOOK = ROOT / "data" / "workbooks" / "20240131 - AVS Budget R0 - Discussion.xlsx"


def imported_workbook():
    """The workbook, imported once and reused until the file changes.

    ``import_workbook`` runs openpyxl over a 1 MB file twice -- once for
    formulas, once for cached values -- and takes 5.4 seconds.  It was being
    called on every ``/api/reconciliation`` request, and the Overview screen
    asks for reconciliation on load, so every cold start paid it before showing
    anything.

    Keyed on the file's mtime, so editing the workbook still re-reads it.
    """
    from qs_importer.pipeline import import_workbook

    stamp = WORKBOOK.stat().st_mtime_ns if WORKBOOK.exists() else 0
    cached = getattr(imported_workbook, "_cached", None)
    if cached is None or cached[0] != stamp:
        imported_workbook._cached = (stamp, import_workbook(WORKBOOK))
    return imported_workbook._cached[1]


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
app = FastAPI(title="DBOT QS Platform", version="0.6.0", docs_url="/api/docs")


# --------------------------------------------------------------------------
# Who is asking
# --------------------------------------------------------------------------
#
# Until now every audit row said "local". A change log that cannot name a
# person is a list of events, not an account of what happened -- which is why
# the workbook carries two shuttering rates Rs 1.25 crore apart with nothing
# saying who set either, or when (C-7).
#
# With no accounts defined the platform is open, so a fresh clone still runs
# with `make run` and no ceremony. The moment somebody creates the first
# account it is closed, and stays closed.

def signed_in(qs_session: str | None = Cookie(default=None)) -> User | None:
    """The user behind this request, or None when nobody is signed in."""
    if not qs_session:
        return None
    row = state.store.session(qs_session)
    if row is None or auth.is_expired(row["expires_at"]):
        if row is not None:
            state.store.end_session(qs_session)
        return None
    record = state.store.user_by_id(row["user_id"])
    if record is None or not record["is_active"]:
        return None
    return User(id=record["id"], email=record["email"], name=record["name"],
                role=Role(record["role"]), is_active=bool(record["is_active"]))


@app.middleware("http")
async def name_the_actor(request, call_next):
    """Put the signed-in person where the audit log will find them.

    This has to be middleware rather than a dependency. FastAPI runs a sync
    endpoint in a threadpool with a *copy* of the context, so a contextvar set
    inside a dependency never reaches the handler -- every audit row kept
    saying "local", which is precisely the failure this feature exists to fix.
    Middleware runs before the copy is taken, so the value travels.
    """
    token = current_actor.set(_actor_for(request.cookies.get(auth.SESSION_COOKIE)))
    try:
        return await call_next(request)
    finally:
        current_actor.reset(token)


def _actor_for(session_token: str | None) -> str:
    if not session_token:
        return "local"
    row = state.store.session(session_token)
    if row is None or auth.is_expired(row["expires_at"]):
        return "local"
    record = state.store.user_by_id(row["user_id"])
    if record is None:
        return "local"
    return f"{record['name']} <{record['email']}>"


#: Whether an account is needed to change anything.
#:
#: Off, for now, at your request: nobody is asked to sign in and every write
#: goes through. The machinery underneath is intact -- accounts, roles,
#: sessions, and the audit log that names whoever made a change -- so turning
#: it back on is this flag, not a rebuild. Until then the audit log records
#: "local", which is honest: it says the change was made at this installation
#: by somebody it cannot name.
ACCOUNTS_REQUIRED = False


def writer(user: User | None = Depends(signed_in)) -> User | None:
    """Refuse a write the signed-in user may not make."""
    if not ACCOUNTS_REQUIRED:
        return user
    if state.store.user_count() == 0:
        return user                         # nobody has set up accounts yet
    if user is None:
        raise HTTPException(401, "sign in to make changes")
    if not user.may_write():
        raise HTTPException(
            403, f"{user.name} is a {user.role.value} and may read but not "
                 f"change project data. A reviewer's job is to disagree with a "
                 f"number, not to replace it.")
    return user


# --------------------------------------------------------------------------
# Read -- everything here is computed by the engine on request
# --------------------------------------------------------------------------

@app.get("/api/me")
def get_me(user: User | None = Depends(signed_in)) -> dict[str, Any]:
    """Who is signed in, and whether accounts are in use at all."""
    return {
        "signed_in": user is not None,
        "accounts_required": ACCOUNTS_REQUIRED,
        "open_access": not ACCOUNTS_REQUIRED or state.store.user_count() == 0,
        "user": None if user is None else {
            "id": user.id, "email": user.email, "name": user.name,
            "role": user.role.value, "may_write": user.may_write(),
            "may_approve": user.may_approve(),
            "may_administer": user.may_administer()},
    }


@app.post("/api/login")
def login(response: Response, payload: dict = Body(...)) -> dict[str, Any]:
    record = state.store.user_by_email(str(payload.get("email", "")))
    password = str(payload.get("password", ""))
    # One message for both failures, so it cannot be used to discover which
    # addresses have accounts.
    if record is None or not record["is_active"] or \
            not auth.verify_password(password, record["password_hash"]):
        raise HTTPException(401, "that email and password do not match")

    token = auth.new_session_token()
    state.store.start_session(token, record["id"], auth.session_expiry())
    response.set_cookie(auth.SESSION_COOKIE, token, httponly=True,
                        samesite="lax", max_age=auth.SESSION_HOURS * 3600)
    return {"ok": True, "user": {"name": record["name"], "role": record["role"]}}


@app.post("/api/logout")
def logout(response: Response,
           qs_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    if qs_session:
        state.store.end_session(qs_session)
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/users")
def list_users(user: User | None = Depends(signed_in)) -> list[dict[str, Any]]:
    if state.store.user_count() and (user is None or not user.may_administer()):
        raise HTTPException(403, "only an admin can see the user list")
    return state.store.users()


@app.post("/api/users")
def create_user(payload: dict = Body(...),
                user: User | None = Depends(signed_in)) -> dict[str, Any]:
    """Add an account.

    The first needs no sign-in -- somebody has to be able to create it -- and
    is an admin by definition. Every one after that needs an admin.
    """
    first = state.store.user_count() == 0
    if not first and (user is None or not user.may_administer()):
        raise HTTPException(403, "only an admin can add users")

    email = str(payload.get("email", "")).strip().lower()
    name = str(payload.get("name", "")).strip()
    role = Role.ADMIN.value if first else str(payload.get("role", "qs"))
    if not email or not name:
        raise HTTPException(400, "an account needs a name and an email address")
    if state.store.user_by_email(email):
        raise HTTPException(409, f"{email} already has an account")
    try:
        Role(role)
        password_hash = auth.hash_password(str(payload.get("password", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    created = state.store.create_user(crud.slug(email)[:40] or "user", email,
                                      name, role, password_hash)
    return {"ok": True, "first_user": first,
            "user": {k: v for k, v in created.items() if k != "password_hash"}}


# --------------------------------------------------------------------------
# The project dashboard
# --------------------------------------------------------------------------

@app.get("/api/dashboard")
def get_dashboard() -> dict[str, Any]:
    """Every project, with enough of its shape to choose between them."""
    out = []
    rows = state.store.projects()
    names = [r["name"] for r in rows]
    for row in rows:
        meta = state.store.project_meta(row["id"])
        entry = {**row, "archived": bool(meta.get("archived")),
                 "updated_at": meta.get("updated_at"),
                 "created_at": meta.get("created_at"),
                 "open": row["id"] == state.project_id,
                 # What a copy of this one would be called. Worked out here
                 # from the names in use, because the screen computes nothing
                 # -- offering "R1" from the browser is how two projects ended
                 # up sharing a name.
                 "next_revision": service.next_revision_name(row["name"], names)}
        try:
            model = state.model if row["id"] == state.project_id \
                else state.store.load(row["id"])
            params = state.params if row["id"] == state.project_id \
                else state.store.load_params(row["id"])
            entry.update(service.project_card(model, params))
        except Exception as exc:                       # a project that will not load
            entry["error"] = str(exc)
        out.append(entry)
    return {"projects": out, "open": state.project_id}


@app.post("/api/projects/open")
def open_project(payload: dict = Body(...),
                 _: User | None = Depends(writer)) -> dict[str, Any]:
    project_id = str(payload.get("project_id", ""))
    if not state.store.exists(project_id):
        raise HTTPException(404, f"no project {project_id!r}")
    state.open(project_id)
    return {"ok": True, **_touched()}


@app.post("/api/projects/new")
def create_project(payload: dict = Body(...),
                   _: User | None = Depends(writer)) -> dict[str, Any]:
    """Start an estimate from nothing.

    Until now the only way to get a project was to copy one, which meant every
    new estimate began life carrying somebody else's rooms.
    """
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "a project needs a name")
    if any(r["name"].strip().casefold() == name.casefold()
           for r in state.store.projects()):
        raise HTTPException(409, f"{name!r} already exists. Give this one a "
                                 f"different name, or copy the existing one.")

    model = service.new_project(name, str(payload.get("city", "")).strip(),
                                str(payload.get("client", "")).strip())
    params = ParameterSet.defaults()
    state.store.save(model, params)
    state.store.set_archived(model.project.id, False)
    state.open(model.project.id)
    return {"ok": True, "project_id": model.project.id, **_touched()}


@app.post("/api/projects/duplicate")
def duplicate_project(payload: dict = Body(...),
                      _: User | None = Depends(writer)) -> dict[str, Any]:
    """Copy a project under a new name.

    A new estimate almost always starts from the last one. Copying gives every
    record a fresh id, so the two can never share a row.
    """
    source_id = str(payload.get("project_id", "")) or state.project_id
    if not source_id or not state.store.exists(source_id):
        raise HTTPException(404, "no such project to copy")

    rows = state.store.projects()
    source = next(r for r in rows if r["id"] == source_id)
    name = str(payload.get("name", "")).strip() or service.next_revision_name(
        source["name"], [r["name"] for r in rows])
    if any(r["name"].strip().casefold() == name.casefold() for r in rows):
        raise HTTPException(409, f"{name!r} already exists. Two projects of one "
                                 f"name cannot be told apart on any screen.")

    model = state.store.load(source_id)
    params = state.store.load_params(source_id)
    copied = service.duplicate(model, name)
    state.store.save(copied, params)
    state.open(copied.project.id)
    return {"ok": True, "project_id": copied.project.id, **_touched()}


@app.post("/api/projects/archive")
def archive_project(payload: dict = Body(...),
                    _: User | None = Depends(writer)) -> dict[str, Any]:
    project_id = str(payload.get("project_id", ""))
    if not state.store.exists(project_id):
        raise HTTPException(404, f"no project {project_id!r}")
    archiving = bool(payload.get("archived", True))
    state.store.set_archived(project_id, archiving)
    return {"ok": True, "archived": archiving}


@app.post("/api/projects/restore")
def restore_project(payload: dict = Body(...),
                    _: User | None = Depends(writer)) -> dict[str, Any]:
    """Bring an archived project back.

    Archiving never deleted anything -- every row stayed where it was -- so
    this only clears the flag. It exists as its own route because "restore"
    is a thing a person does, and asking them to archive something with
    ``archived: false`` is not an interface.
    """
    project_id = str(payload.get("project_id", ""))
    if not state.store.exists(project_id):
        raise HTTPException(404, f"no project {project_id!r}")
    state.store.set_archived(project_id, False)
    return {"ok": True, "archived": False}


# --------------------------------------------------------------------------
# Excel export
# --------------------------------------------------------------------------

@app.get("/api/export.xlsx")
def export_workbook() -> Response:
    """The estimate as a workbook, for sending out.

    Formulas, not values: a reader can see how every figure was reached and
    check it in Excel. The work still happens here -- this is the copy that
    leaves the building.
    """
    model, params = state.require()
    data = service.export_workbook(model, params)
    filename = f"{model.project.code or 'estimate'}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


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


@app.get("/api/unit-types/{unit_type_id}/kitchen-platforms")
def get_kitchen_platforms(unit_type_id: str) -> dict[str, Any]:
    """The counters in this unit type's rooms.

    Its own call rather than part of the rooms payload: the rooms response is
    already the largest on the site, and a kitchen tab that is not open should
    not be costing every other screen bytes.
    """
    model, params = state.require()
    try:
        return service.kitchen_platforms(model, params, unit_type_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


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


@app.get("/api/takeoff/derivation")
def get_takeoff_derivation(room_id: str, finish_slot_id: str,
                           unit_type_id: str | None = None,
                           floor_height_m: float | None = None) -> dict[str, Any]:
    """The working behind one take-off figure.

    The list endpoint used to carry a derivation on every line -- 54% of a 2 MB
    payload, for three panels a QS opens one at a time.
    """
    model, params = state.require()
    found = service.takeoff_derivation(model, params, room_id, finish_slot_id,
                                       unit_type_id, floor_height_m)
    if found is None:
        raise HTTPException(404, "no take-off line for that room and finish")
    return found


@app.get("/api/cost-lines")
def get_cost_lines() -> dict[str, Any]:
    model, params = state.require()
    return service.cost_lines(model, params)


@app.get("/api/summary")
def get_summary() -> dict[str, Any]:
    model, params = state.require()
    return service.project_summary(model, params)


@app.get("/api/usage/{kind}/{subject:path}")
def get_usage(kind: str, subject: str) -> dict[str, Any]:
    """Everything that depends on one parameter, rate or room."""
    model, params = state.require()
    try:
        return service.usage(model, params, kind, subject)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/room-type-mapping")
def get_room_type_mapping() -> dict[str, Any]:
    model, params = state.require()
    return {"mappings": service.room_type_mapping(model, params),
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
    from qs_importer.reconcile import build_lines

    result = imported_workbook()
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
def set_mix(payload: dict = Body(...),
            _: User | None = Depends(writer)) -> dict[str, Any]:
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
def set_floor(floor_id: str, payload: dict = Body(...),
              _: User | None = Depends(writer)) -> dict[str, Any]:
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
def set_room(room_id: str, payload: dict = Body(...),
             _: User | None = Depends(writer)) -> dict[str, Any]:
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
def set_rate(rate_item_id: str, payload: dict = Body(...),
             _: User | None = Depends(writer)) -> dict[str, Any]:
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
def set_opening_type(opening_type_id: str, payload: dict = Body(...),
                     _: User | None = Depends(writer)) -> dict[str, Any]:
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
def set_room_opening(room_opening_id: str, payload: dict = Body(...),
                     _: User | None = Depends(writer)) -> dict[str, Any]:
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
def add_room_opening(room_id: str, payload: dict = Body(...),
                     _: User | None = Depends(writer)) -> dict[str, Any]:
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
def set_parameter(key: str, payload: dict = Body(...),
                  _: User | None = Depends(writer)) -> dict[str, Any]:
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
def create_record(name: str, payload: dict = Body(default={}),
                  _: User | None = Depends(writer)) -> dict[str, Any]:
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
def update_record(name: str, entity_id: str, payload: dict = Body(...),
                  _: User | None = Depends(writer)) -> dict[str, Any]:
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
def delete_record(name: str, entity_id: str,
                  _: User | None = Depends(writer)) -> dict[str, Any]:
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

#: Static assets must revalidate every time -- that is what stops a pulled build
#: from being invisible.  ``no-cache`` does exactly that, and unlike
#: ``no-store`` it still lets the browser keep the file and take a 304, so a
#: reload does not re-download all fifteen modules.
REVALIDATE = "no-cache"


class NoStoreStatic(StaticFiles):
    """Static files the browser must revalidate before reusing."""

    def file_response(self, *args: Any, **kwargs: Any):  # noqa: ANN201
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = REVALIDATE
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
