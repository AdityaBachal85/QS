"""Persistence must not change a single number."""

import dataclasses

import pytest

from qs_app.store import TABLES, Store
from qs_engine.model import OpeningKind, UnitTypeRoom
from qs_engine.rules.rate_buildup import effective_rate
from qs_engine.rules.schedule import total_openings
from qs_engine.rules.unit_area import unit_type_total_sqft


@pytest.fixture(scope="module")
def saved(avs, tmp_path_factory):
    store = Store(tmp_path_factory.mktemp("db") / "qs.db")
    store.save(avs.model, avs.params)
    return store, avs


def test_round_trip_keeps_every_row(saved):
    store, avs = saved
    back = store.load(avs.model.project.id)
    for _, _, attr in TABLES:
        if attr is None:
            continue
        assert len(getattr(back, attr)) == len(getattr(avs.model, attr)), attr


def test_round_trip_keeps_every_number(saved):
    """The figures after a save and load are identical, not merely close."""
    store, avs = saved
    back = store.load(avs.model.project.id)
    params = store.load_params(avs.model.project.id)

    for unit in avs.model.unit_types:
        before = unit_type_total_sqft(unit.id, avs.model, avs.params).value
        after = unit_type_total_sqft(unit.id, back, params).value
        assert after == before, unit.code

    assert total_openings(back, (OpeningKind.DOOR,)).value == \
        total_openings(avs.model, (OpeningKind.DOOR,)).value

    for item in avs.model.rate_items[:40]:
        before = effective_rate(item, avs.model, avs.params).value
        after = effective_rate(back.rate_item(item.id), back, params).value
        assert after == before, item.description


def test_derived_values_have_no_columns(saved):
    """``area_sqft`` is a function, so there is nowhere to store one.

    That is the storage-layer half of C-3: the workbook let a perimeter be
    pasted into an area column because the column existed.
    """
    store, _ = saved
    columns = {row[1] for row in
               store._conn.execute('PRAGMA table_info("unit_type_room")')}
    assert "carpet_area_sqm" in columns
    assert "area_sqft" not in columns
    assert "area_sqft" not in {f.name for f in dataclasses.fields(UnitTypeRoom)}

    opening_columns = {row[1] for row in
                       store._conn.execute('PRAGMA table_info("opening_type")')}
    assert "width_m" in opening_columns and "height_m" in opening_columns
    assert "area_sqm" not in opening_columns


def test_ids_are_the_primary_key(saved):
    """Nothing is addressed by row position, at any layer (C-6)."""
    store, _ = saved
    for table, _, _ in TABLES:
        pk = [row[1] for row in store._conn.execute(f'PRAGMA table_info("{table}")')
              if row[5]]
        assert pk == ["id"], table


def test_audit_log_records_old_and_new(saved):
    store, avs = saved
    store.log(avs.model.project.id, "rate_revision", "r1", "basic_rate", 45, 50,
              reason="revised quote")
    entry = store.audit(avs.model.project.id)[0]
    assert entry["old_value"] == "45" and entry["new_value"] == "50"
    assert entry["reason"] == "revised quote"


def test_a_parameter_declared_after_the_save_still_loads(saved, tmp_path):
    """A stored parameter set is a snapshot, not the whole vocabulary.

    The rows in `project_parameter` were written by whatever version of the
    engine saved the project, so a parameter declared since then is simply
    absent from them. Rebuilt from the rows alone, that absence became the
    answer: `params["construction_area_sqft"]` raised "unknown project
    parameter", which reads as a coding mistake and is really a project saved
    last week. Every new parameter broke every existing project the same way,
    and the empty-rows guard only ever covered the case where nothing had been
    saved at all.
    """
    from qs_engine.params import ParameterSet

    _, avs = saved
    store = Store(tmp_path / "old.db")
    store.save(avs.model, avs.params)

    # A project saved before `construction_area_sqft` existed: every other row
    # present, that one never written.
    store._conn.execute(
        'DELETE FROM "project_parameter" WHERE "key" = ?',
        ("construction_area_sqft",),
    )
    store._conn.commit()

    back = store.load_params(avs.model.project.id)
    declared = ParameterSet.defaults()
    assert back["construction_area_sqft"] == declared["construction_area_sqft"]

    # And every other parameter still comes from the file rather than being
    # quietly reset to its default alongside it.
    changed = avs.params.with_value("post_construction_rate_psf", 99.0,
                                    reason="test")
    store.save_params(avs.model.project.id, changed)
    store._conn.execute(
        'DELETE FROM "project_parameter" WHERE "key" = ?',
        ("construction_area_sqft",),
    )
    store._conn.commit()
    back = store.load_params(avs.model.project.id)
    assert back["post_construction_rate_psf"] == 99.0
    assert back["construction_area_sqft"] == declared["construction_area_sqft"]
