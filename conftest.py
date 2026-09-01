"""Shared fixtures.

The workbook takes a few seconds to stage, so it loads once per session and
every test reads the same imported model.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "packages" / "engine"))
sys.path.insert(0, str(ROOT / "packages" / "importer"))

WORKBOOK = ROOT / "data" / "workbooks" / "20240131 - AVS Budget R0 - Discussion.xlsx"


@pytest.fixture(scope="session")
def avs():
    """The AVS workbook, imported. The reference model for every gate."""
    from qs_importer.pipeline import import_workbook
    if not WORKBOOK.exists():
        pytest.skip(f"workbook not present at {WORKBOOK}")
    return import_workbook(WORKBOOK)


@pytest.fixture(scope="session")
def model(avs):
    return avs.model


@pytest.fixture(scope="session")
def params(avs):
    return avs.params


@pytest.fixture(scope="session")
def wb(avs):
    return avs.workbook


def unit_type(model, code):
    for ut in model.unit_types:
        if ut.code == code:
            return ut
    raise AssertionError(f"no unit type {code!r}")
