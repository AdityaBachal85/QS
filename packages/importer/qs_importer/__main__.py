"""``python -m qs_importer <workbook>`` -- run the reconciliation."""

from __future__ import annotations

import sys
from pathlib import Path

from .pipeline import import_workbook
from .reconcile import Status, build_lines, render

DEFAULT = Path("data/workbooks/20240131 - AVS Budget R0 - Discussion.xlsx")


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not path.exists():
        print(f"workbook not found: {path}", file=sys.stderr)
        return 2
    result = import_workbook(path)
    print(render(result))
    failed = [l for l in build_lines(result) if l.status is Status.FAIL]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
