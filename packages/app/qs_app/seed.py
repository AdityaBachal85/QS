"""Put the AVS workbook into the local database.

Nothing is auto-corrected on the way in. Defects import as they stand, get
flagged by the validation engine, and change only when somebody approves the
change -- which is why the reconciliation report can attribute every difference.

**This re-imports every time**, so hosting from the terminal always shows the
current build's data. That matters because a good deal of what the platform
knows is established at import: the door and window rates, for instance, are
read from ``D&W Schedule`` column F and attached to the opening types by
``map_opening_types``. A database written by an older build simply does not have
them, and every opening then prices at nothing -- which looks exactly like a
broken screen.

It is not destructive: the previous database is copied to ``qs.db.bak`` first.
``--keep`` (or ``make run KEEP=1``) leaves an existing database alone.

This is a build-phase default. When the project dashboard arrives and edits are
stored properly, this flips to preserving them.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from .server import DB_PATH, WORKBOOK
from .store import Store


def backup(db_path: Path) -> Path | None:
    """Copy the database aside, through SQLite rather than the filesystem.

    The database runs in WAL mode, so the ``.db`` file on its own can be behind
    the write-ahead log. ``sqlite3``'s own backup API takes a consistent copy
    including anything still in the WAL; ``cp`` would not.
    """
    if not db_path.exists():
        return None
    target = db_path.with_suffix(db_path.suffix + ".bak")
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def seed(db_path: Path = DB_PATH, workbook: Path = WORKBOOK,
         *, keep: bool = False) -> str:
    from qs_importer.pipeline import import_workbook

    store = Store(db_path)
    existing = store.project_ids()
    if existing and keep:
        print(f"{db_path.name} already holds: {', '.join(existing)}"
              f"  (kept -- drop KEEP=1 to re-import)")
        return existing[0]

    if not workbook.exists():
        raise SystemExit(f"workbook not found at {workbook}")

    saved = backup(db_path) if existing else None
    if saved:
        print(f"previous database copied to {saved.name}")

    print(f"importing {workbook.name} ...")
    result = import_workbook(workbook)
    store.save(result.model, result.params)

    counts = ", ".join(f"{k} {v}" for k, v in result.counts.items())
    print(f"  {counts}")
    priced = sum(1 for o in result.model.opening_types if o.rate_item_id)
    print(f"  {priced} of {len(result.model.opening_types)} opening types priced")
    if result.warnings:
        print(f"  {len(result.warnings)} import notes -- see the Validation screen")
    print(f"saved to {db_path}")
    return result.model.project.id


if __name__ == "__main__":
    seed(keep="--keep" in sys.argv)
