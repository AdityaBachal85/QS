"""Persistence: a ProjectModel in one SQLite file.

All SQL lives in this module. Nothing else in the codebase knows the database
exists, so moving to Postgres later means rewriting this file and nothing else.

Two rules the schema enforces:

* **Derived values have no columns.**  Tables are built from the *fields* of each
  dataclass, and derived values are properties rather than fields, so there is no
  column for ``area_sqft`` to be written into.  That is the same guarantee the
  model makes, carried down to the storage layer (C-3).
* **Ids are the only linkage.**  Every row is keyed and referenced by its id.
  Nothing depends on insertion order, so rows can be added, deleted or re-sorted
  freely (C-6).
"""

from __future__ import annotations

import contextvars
import dataclasses
import sqlite3
import typing
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from qs_engine import model as M
from qs_engine.params import Parameter, ParameterSet

#: (table name, dataclass, the ProjectModel attribute holding the list).
#: ``None`` for the project itself, which is a single row.
TABLES: tuple[tuple[str, type, str | None], ...] = (
    ("project", M.Project, None),
    ("building", M.Building, "buildings"),
    ("floor", M.Floor, "floors"),
    ("unit_type", M.UnitType, "unit_types"),
    ("floor_unit_mix", M.FloorUnitMix, "floor_unit_mix"),
    ("room_type", M.RoomType, "room_types"),
    ("unit_type_room", M.UnitTypeRoom, "unit_type_rooms"),
    ("finish_slot", M.FinishSlot, "finish_slots"),
    ("room_finish_spec", M.RoomFinishSpec, "room_finish_specs"),
    ("kitchen_platform", M.KitchenPlatform, "kitchen_platforms"),
    ("opening_type", M.OpeningType, "opening_types"),
    ("room_opening", M.RoomOpening, "room_openings"),
    ("rate_item", M.RateItem, "rate_items"),
    ("rate_revision", M.RateRevision, "rate_revisions"),
    ("project_rate", M.ProjectRate, "project_rates"),
    ("cost_section", M.CostSection, "cost_sections"),
    ("cost_line", M.CostLine, "cost_lines"),
    ("cost_line_qty", M.CostLineQty, "cost_line_qtys"),
)

#: Added to every table so a whole project loads with one WHERE clause. Named
#: distinctly because several entities carry their own ``project_id`` field.
OWNER = "_owner_project"

#: Who is making the change now.
#:
#: Every audit row said "local" until accounts existed. The actor belongs to
#: the request rather than to any one call, so it travels here instead of
#: growing an argument on fifteen call sites -- and a background task that sets
#: nothing still records something truthful.
current_actor: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_actor", default="local")


def _hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _is_optional(hint: Any) -> bool:
    return get_origin(hint) in (typing.Union, getattr(__import__("types"), "UnionType", None)) \
        and type(None) in get_args(hint)


def _base_type(hint: Any) -> Any:
    """Strip ``| None`` to get at the underlying type."""
    if _is_optional(hint):
        args = [a for a in get_args(hint) if a is not type(None)]
        return args[0] if args else str
    return hint


def _sql_type(hint: Any) -> str:
    base = _base_type(hint)
    if isinstance(base, type) and issubclass(base, Enum):
        return "TEXT"
    if base is float:
        return "REAL"
    if base is bool or base is int:
        return "INTEGER"
    return "TEXT"


def _to_sql(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return int(value)
    return value


def _from_sql(value: Any, hint: Any) -> Any:
    if value is None:
        return None
    base = _base_type(hint)
    if isinstance(base, type) and issubclass(base, Enum):
        return base(value)
    if base is bool:
        return bool(value)
    if base is int:
        return int(value)
    if base is float:
        return float(value)
    return value


def _columns(cls: type) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """Reads and writes whole projects.

    Deliberately coarse: the UI edits one project at a time, and rewriting a
    project's rows inside a transaction is both simpler and safer than tracking
    per-row dirty state. If that ever becomes slow, the fix is per-entity
    upserts -- not a different design.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.create_schema()

    def close(self) -> None:
        self._conn.close()

    # -- schema ------------------------------------------------------------

    def create_schema(self) -> None:
        cur = self._conn.cursor()
        for table, cls, _ in TABLES:
            hints = _hints(cls)
            cols = [f"{OWNER} TEXT NOT NULL"]
            for name in _columns(cls):
                nullable = "" if name == "id" else ""
                cols.append(f'"{name}" {_sql_type(hints[name])}{nullable}')
            cur.execute(
                f'CREATE TABLE IF NOT EXISTS "{table}" ('
                + ", ".join(cols)
                + ', PRIMARY KEY ("id"))'
            )
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS "ix_{table}_owner" '
                f'ON "{table}" ("{OWNER}")'
            )
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "project_parameter" ('
            f'"{OWNER}" TEXT NOT NULL, "key" TEXT NOT NULL, "value" REAL NOT NULL, '
            f'"unit" TEXT, "description" TEXT, "source" TEXT, '
            f'PRIMARY KEY ("{OWNER}", "key"))'
        )
        # Users and sessions live outside the per-project tables: they are not
        # part of a project revision and must survive one being replaced.
        cur.execute(
            'CREATE TABLE IF NOT EXISTS "app_user" ('
            '"id" TEXT PRIMARY KEY, "email" TEXT NOT NULL UNIQUE, '
            '"name" TEXT NOT NULL, "role" TEXT NOT NULL, '
            '"password_hash" TEXT NOT NULL, "is_active" INTEGER NOT NULL DEFAULT 1, '
            '"created_at" TEXT NOT NULL)'
        )
        cur.execute(
            'CREATE TABLE IF NOT EXISTS "app_session" ('
            '"token" TEXT PRIMARY KEY, "user_id" TEXT NOT NULL, '
            '"created_at" TEXT NOT NULL, "expires_at" TEXT NOT NULL)'
        )
        cur.execute('CREATE INDEX IF NOT EXISTS "ix_session_user" '
                    'ON "app_session" ("user_id")')
        # Project metadata the dashboard needs and a ProjectModel does not
        # carry -- when it was touched, and whether it is still live.
        cur.execute(
            'CREATE TABLE IF NOT EXISTS "project_meta" ('
            '"project_id" TEXT PRIMARY KEY, "created_at" TEXT, '
            '"updated_at" TEXT, "archived" INTEGER NOT NULL DEFAULT 0, '
            '"created_by" TEXT)'
        )
        cur.execute(
            'CREATE TABLE IF NOT EXISTS "audit_log" ('
            '"id" INTEGER PRIMARY KEY AUTOINCREMENT, "at" TEXT NOT NULL, '
            '"project_id" TEXT NOT NULL, "actor" TEXT, "entity" TEXT, '
            '"entity_id" TEXT, "field" TEXT, "old_value" TEXT, '
            '"new_value" TEXT, "reason" TEXT)'
        )
        self._conn.commit()

    # -- projects ----------------------------------------------------------

    def project_ids(self) -> list[str]:
        rows = self._conn.execute('SELECT "id" FROM "project" ORDER BY "id"').fetchall()
        return [r["id"] for r in rows]

    def projects(self) -> list[dict[str, Any]]:
        rows = self._conn.execute('SELECT * FROM "project" ORDER BY "name"').fetchall()
        return [{k: r[k] for k in r.keys() if k != OWNER} for r in rows]

    def exists(self, project_id: str) -> bool:
        row = self._conn.execute(
            'SELECT 1 FROM "project" WHERE "id" = ?', (project_id,)
        ).fetchone()
        return row is not None

    # -- save / load -------------------------------------------------------

    def save(self, model: M.ProjectModel, params: ParameterSet | None = None) -> None:
        """Replace a project's rows, in one transaction."""
        owner = model.project.id
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")
            for table, cls, attr in TABLES:
                cur.execute(f'DELETE FROM "{table}" WHERE "{OWNER}" = ?', (owner,))
                items = [model.project] if attr is None else getattr(model, attr)
                if not items:
                    continue
                cols = _columns(cls)
                placeholders = ", ".join("?" * (len(cols) + 1))
                names = ", ".join(f'"{c}"' for c in [OWNER, *cols])
                cur.executemany(
                    f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
                    [tuple([owner, *(_to_sql(getattr(i, c)) for c in cols)])
                     for i in items],
                )
            if params is not None:
                cur.execute('DELETE FROM "project_parameter" WHERE "{}" = ?'
                            .format(OWNER), (owner,))
                cur.executemany(
                    f'INSERT INTO "project_parameter" '
                    f'("{OWNER}", "key", "value", "unit", "description", "source") '
                    f"VALUES (?, ?, ?, ?, ?, ?)",
                    [(owner, p.key, p.value, p.unit, p.description, p.source)
                     for p in params],
                )
            now = _now()
            cur.execute(
                'INSERT INTO "project_meta" ("project_id", "created_at", '
                '"updated_at") VALUES (?, ?, ?) '
                'ON CONFLICT("project_id") DO UPDATE SET "updated_at" = ?',
                (owner, now, now, now))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def load(self, project_id: str) -> M.ProjectModel:
        cur = self._conn.cursor()
        row = cur.execute('SELECT * FROM "project" WHERE "id" = ?',
                          (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"no project {project_id!r} in {self.path.name}")

        def build(cls: type, r: sqlite3.Row):
            hints = _hints(cls)
            return cls(**{c: _from_sql(r[c], hints[c]) for c in _columns(cls)})

        model = M.ProjectModel(project=build(M.Project, row))
        for table, cls, attr in TABLES:
            if attr is None:
                continue
            rows = cur.execute(f'SELECT * FROM "{table}" WHERE "{OWNER}" = ?',
                               (project_id,)).fetchall()
            getattr(model, attr).extend(build(cls, r) for r in rows)
        return model

    def load_params(self, project_id: str) -> ParameterSet:
        rows = self._conn.execute(
            f'SELECT * FROM "project_parameter" WHERE "{OWNER}" = ?', (project_id,)
        ).fetchall()
        if not rows:
            return ParameterSet.defaults()
        return ParameterSet({
            r["key"]: Parameter(r["key"], r["value"], r["unit"] or "",
                                r["description"] or "", r["source"] or "")
            for r in rows
        })

    def save_params(self, project_id: str, params: ParameterSet) -> None:
        cur = self._conn.cursor()
        cur.execute(f'DELETE FROM "project_parameter" WHERE "{OWNER}" = ?',
                    (project_id,))
        cur.executemany(
            f'INSERT INTO "project_parameter" '
            f'("{OWNER}", "key", "value", "unit", "description", "source") '
            f"VALUES (?, ?, ?, ?, ?, ?)",
            [(project_id, p.key, p.value, p.unit, p.description, p.source)
             for p in params],
        )
        self._conn.commit()

    # -- users and sessions -------------------------------------------------

    def create_user(self, user_id: str, email: str, name: str, role: str,
                    password_hash: str) -> dict[str, Any]:
        self._conn.execute(
            'INSERT INTO "app_user" ("id", "email", "name", "role", '
            '"password_hash", "is_active", "created_at") VALUES (?, ?, ?, ?, ?, 1, ?)',
            (user_id, email.strip().lower(), name, role, password_hash, _now()))
        self._conn.commit()
        return self.user_by_email(email)

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._conn.execute('SELECT * FROM "app_user" WHERE "email" = ?',
                                 (email.strip().lower(),)).fetchone()
        return dict(row) if row else None

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        row = self._conn.execute('SELECT * FROM "app_user" WHERE "id" = ?',
                                 (user_id,)).fetchone()
        return dict(row) if row else None

    def users(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            'SELECT "id", "email", "name", "role", "is_active", "created_at" '
            'FROM "app_user" ORDER BY "name"').fetchall()
        return [dict(r) for r in rows]

    def user_count(self) -> int:
        return self._conn.execute(
            'SELECT COUNT(*) AS n FROM "app_user"').fetchone()["n"]

    def set_user_active(self, user_id: str, active: bool) -> None:
        self._conn.execute('UPDATE "app_user" SET "is_active" = ? WHERE "id" = ?',
                           (1 if active else 0, user_id))
        self._conn.commit()

    def start_session(self, token: str, user_id: str, expires_at: str) -> None:
        self._conn.execute(
            'INSERT INTO "app_session" ("token", "user_id", "created_at", '
            '"expires_at") VALUES (?, ?, ?, ?)',
            (token, user_id, _now(), expires_at))
        self._conn.commit()

    def session(self, token: str) -> dict[str, Any] | None:
        row = self._conn.execute('SELECT * FROM "app_session" WHERE "token" = ?',
                                 (token,)).fetchone()
        return dict(row) if row else None

    def end_session(self, token: str) -> None:
        self._conn.execute('DELETE FROM "app_session" WHERE "token" = ?', (token,))
        self._conn.commit()

    def purge_expired_sessions(self, now: str) -> int:
        cur = self._conn.execute('DELETE FROM "app_session" WHERE "expires_at" <= ?',
                                 (now,))
        self._conn.commit()
        return cur.rowcount

    # -- project metadata ---------------------------------------------------

    def project_meta(self, project_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            'SELECT * FROM "project_meta" WHERE "project_id" = ?',
            (project_id,)).fetchone()
        return dict(row) if row else {"project_id": project_id, "created_at": None,
                                      "updated_at": None, "archived": 0,
                                      "created_by": None}

    def set_archived(self, project_id: str, archived: bool) -> None:
        self._conn.execute(
            'INSERT INTO "project_meta" ("project_id", "archived", "updated_at") '
            'VALUES (?, ?, ?) ON CONFLICT("project_id") DO UPDATE SET '
            '"archived" = ?, "updated_at" = ?',
            (project_id, int(archived), _now(), int(archived), _now()))
        self._conn.commit()

    def delete_project(self, project_id: str) -> None:
        """Remove a project and every row that belongs to it."""
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")
            for table, _, _ in TABLES:
                cur.execute(f'DELETE FROM "{table}" WHERE "{OWNER}" = ?',
                            (project_id,))
            cur.execute(f'DELETE FROM "project_parameter" WHERE "{OWNER}" = ?',
                        (project_id,))
            cur.execute('DELETE FROM "project_meta" WHERE "project_id" = ?',
                        (project_id,))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- audit -------------------------------------------------------------

    def log(self, project_id: str, entity: str, entity_id: str, field: str,
            old: Any, new: Any, *, actor: str | None = None,
            reason: str = "") -> None:
        """Record a change.

        The workbook has no equivalent: two shuttering rates sit one sheet apart
        with nothing saying who set either, or when (C-7). Every write through
        the API lands here.
        """
        from datetime import datetime, timezone
        self._conn.execute(
            'INSERT INTO "audit_log" ("at", "project_id", "actor", "entity", '
            '"entity_id", "field", "old_value", "new_value", "reason") '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), project_id,
             actor or current_actor.get(), entity, entity_id, field,
             None if old is None else str(old),
             None if new is None else str(new), reason),
        )
        self._conn.commit()

    def audit(self, project_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            'SELECT * FROM "audit_log" WHERE "project_id" = ? '
            'ORDER BY "id" DESC LIMIT ?', (project_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
