"""The screens, read as source.

There is no JavaScript runtime in the test suite, so these read the screen
files the way a reviewer would and assert the properties that went wrong
before: a grey cell that does nothing when you click it, and a label dressed
up as a calculation.

Reading source is a blunt instrument and it is the right one here. The failure
these guard against is not a logic error -- it is a column added without a
handler, which is exactly the kind of thing source can see and a unit test
cannot.
"""

import re
from pathlib import Path

import pytest

SCREENS = Path(__file__).resolve().parents[3] / "web" / "screens"
WEB = SCREENS.parent

#: `{ key: 'x', ... kind: 'derived'` -- a column declared as a computed figure.
DERIVED = re.compile(r"\{\s*key:\s*'([^']+)'[^\n]*?kind:\s*'derived'")
GRIDS = re.compile(r"createGrid\(")


def screens():
    return sorted(p for p in SCREENS.glob("*.js") if p.name != "login.js")


def test_there_are_screens_to_check():
    assert len(screens()) >= 14


@pytest.mark.parametrize("path", screens(), ids=lambda p: p.stem)
def test_every_screen_that_draws_a_figure_can_explain_one(path):
    """A calculated cell must open its working.

    Before this, `kind: 'derived'` meant both "this is computed" and "you
    cannot type here", so `Unit` = SQM rendered in the same grey as a Rs 9
    crore total and invited the same click -- and seven screens had no handler
    at all. The grid now falls back rather than going silent, but a screen that
    draws figures and explains none of them is still a screen nobody finished.
    """
    source = path.read_text()
    columns = DERIVED.findall(source)
    if not columns:
        return
    assert "onDerivedClick" in source, (
        f"{path.name} draws {len(columns)} calculated column(s) "
        f"({', '.join(sorted(set(columns))[:5])}) and explains none of them")


@pytest.mark.parametrize("path", screens(), ids=lambda p: p.stem)
def test_no_screen_calls_a_label_a_calculation(path):
    """Units, kinds, workbook refs and status text are `note`, not `derived`.

    A cell that is grey because you cannot type in it is not the same as a cell
    that is grey because a rule produced it, and only the second has anything
    to open.
    """
    source = path.read_text()
    mislabelled = [key for key in DERIVED.findall(source)
                   if key in {"unit", "kind", "rate_unit", "excel_ref", "city",
                              "message", "source", "description", "category",
                              "confirmed", "updated_at", "_source", "_src"}]
    assert not mislabelled, (
        f"{path.name} declares {mislabelled} as calculated. These are labels: "
        f"use kind: 'note' so they do not invite a click with nothing behind it")


def test_the_grid_never_lets_a_calculated_cell_go_quiet():
    """The structural half: a click always opens something."""
    grid = (WEB / "grid.js").read_text()
    assert "function explain(" in grid
    assert "function fallback(" in grid
    # A handler may be async; a promise must be waited on rather than read as
    # "handled" simply for being truthy.
    assert "typeof handled.then === 'function'" in grid
    # A handler has to *say* it handled the click. Returning nothing is what a
    # handler does when it has no case for a column, and that is exactly when
    # the fallback is needed -- so silence must not read as "handled".
    assert "if (!handled) fallback(row, col);" in grid


def test_a_note_cell_does_not_pretend_to_be_clickable():
    grid = (WEB / "grid.js").read_text()
    style = (WEB / "style.css").read_text()
    assert "classes.push('derived', 'note')" in grid
    assert "classes.push('derived', 'clickable')" in grid
    assert "td.derived.note { cursor: default;" in style
    assert "td.derived.clickable { cursor: pointer; }" in style
