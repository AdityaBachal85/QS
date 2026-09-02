"""First run: put the AVS workbook into the local database.

Nothing is auto-corrected on the way in. Defects import as they stand, get
flagged by the validation engine, and change only when somebody approves the
change -- which is why the reconciliation report can attribute every difference.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .server import DB_PATH, WORKBOOK
from .store import Store


def seed(db_path: Path = DB_PATH, workbook: Path = WORKBOOK,
         *, force: bool = False) -> str:
    from qs_importer.pipeline import import_workbook

    store = Store(db_path)
    existing = store.project_ids()
    if existing and not force:
        print(f"{db_path.name} already holds: {', '.join(existing)}  "
              f"(use --force to reimport)")
        return existing[0]

    if not workbook.exists():
        raise SystemExit(f"workbook not found at {workbook}")

    print(f"importing {workbook.name} ...")
    result = import_workbook(workbook)
    store.save(result.model, result.params)
    counts = ", ".join(f"{k} {v}" for k, v in result.counts.items())
    print(f"  {counts}")
    if result.warnings:
        print(f"  {len(result.warnings)} import notes -- see the Validation screen")
    print(f"saved to {db_path}")
    return result.model.project.id


if __name__ == "__main__":
    seed(force="--force" in sys.argv)
