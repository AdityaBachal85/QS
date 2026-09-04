"""The kitchen counters.

A kitchen is not measured like other rooms.  Its dado does not run round the
perimeter -- it runs along the counters -- so the quantity comes from the
platform lengths:

    Above = (main x above) + (service x above)
    Below = (main x below) + (service x below)

Written one term per counter, never factored.  ``(3 x 1.5) + (2 x 1.5)`` and
``(3 + 2) x 1.5`` agree today and are not the same statement: the first says
each counter is measured and the results added, which is what a QS is doing,
and it survives the day a service counter takes a different height.  The
expression is asserted here as a string so that a later tidy-up cannot quietly
factor it.
"""

import pytest

from qs_engine.model import (KitchenPlatform, ProjectModel, Project, RoomType,
                             RoomCategory, UnitType, UnitTypeRoom)
from qs_engine.params import ParameterSet
from qs_engine.rules.room_qty import (QTY_RULES, MissingKitchenPlatformError,
                                      qty_dado_above_platform,
                                      qty_dado_below_platform,
                                      qty_kitchen_platform,
                                      qty_service_platform)


@pytest.fixture
def kitchen():
    """A one-room project: the example, exactly as it was given.

    MP 3, SP 2, above 1.5, below 0.9 -> 7.50 and 4.50.
    """
    model = ProjectModel(project=Project(id="p", code="EX", name="Example", city=""))
    room_type = RoomType(id="rt", project_id="p", name="Cocina",
                         category=RoomCategory.KITCHEN)
    unit_type = UnitType(id="ut", project_id="p", code="Type A")
    room = UnitTypeRoom(id="r", unit_type_id="ut", room_type_id="rt", seq=0,
                        label="Cocina", carpet_area_sqm=6.0, perimeter_m=10.0)
    model.room_types.append(room_type)
    model.unit_types.append(unit_type)
    model.unit_type_rooms.append(room)
    model.kitchen_platforms.append(KitchenPlatform(
        id="k", unit_type_room_id="r",
        main_platform_m=3.0, service_platform_m=2.0,
        dado_above_m=1.5, dado_below_m=0.9))
    return model, room, ParameterSet.defaults()


def test_the_example_as_it_was_given(kitchen):
    model, room, params = kitchen
    above = qty_dado_above_platform(room, model, params)
    below = qty_dado_below_platform(room, model, params)
    assert above.value.value == pytest.approx(7.5)
    assert below.value.value == pytest.approx(4.5)
    assert above.value.unit.code == below.value.unit.code == "SQM"


def test_the_working_reads_one_term_per_counter_and_is_not_factored(kitchen):
    model, room, params = kitchen
    assert qty_dado_above_platform(room, model, params).derivation.expression == \
        "(3 x 1.5) + (2 x 1.5)"
    assert qty_dado_below_platform(room, model, params).derivation.expression == \
        "(3 x 0.9) + (2 x 0.9)"


def test_each_counter_names_itself_and_says_where_it_came_from(kitchen):
    model, room, params = kitchen
    inputs = qty_dado_above_platform(room, model, params).derivation.inputs
    assert [i.name for i in inputs] == [
        "main platform", "service platform", "dado above the counter"]
    assert all("Kitchen platforms tab" in i.source for i in inputs)


def test_the_counter_runs_are_inputs_not_arithmetic(kitchen):
    model, room, params = kitchen
    assert qty_kitchen_platform(room, model, params).value.value == 3.0
    assert qty_service_platform(room, model, params).value.value == 2.0
    assert qty_kitchen_platform(room, model, params).value.unit.code == "RM"


def test_a_service_counter_may_take_its_own_height(kitchen):
    """What the factored form could not express.

    ``(3 + 2) x 1.5`` has nowhere to put a second height; folding over the
    counters does.  The rule takes one height today -- this fixes the shape
    that lets it take two without the arithmetic having to change.
    """
    model, room, params = kitchen
    platform = model.kitchen_platform("r")
    terms = [run * 1.5 for _, run in platform.runs]
    assert terms == [4.5, 3.0]
    assert sum(terms) == pytest.approx(
        qty_dado_above_platform(room, model, params).value.value)


def test_a_room_called_anything_at_all_measures_the_same_way(kitchen):
    """Non-negotiable 5: nothing depends on the word "Kitchen"."""
    model, room, params = kitchen
    model.room_types[0].name = "Servant Pantry & Wet Bar"
    model.room_types[0].category = RoomCategory.HABITABLE
    assert qty_dado_above_platform(room, model, params).value.value == \
        pytest.approx(7.5)


def test_a_counter_with_no_run_is_not_a_counter_of_zero_length(kitchen):
    """An office Pantry has a service run and no main one."""
    model, room, params = kitchen
    model.kitchen_platforms[0].main_platform_m = 0.0
    assert qty_dado_above_platform(room, model, params).derivation.expression == "(2 x 1.5)"
    assert qty_dado_above_platform(room, model, params).value.value == \
        pytest.approx(3.0)
    with pytest.raises(MissingKitchenPlatformError):
        qty_kitchen_platform(room, model, params)


def test_a_kitchen_with_no_counters_is_unmeasured_never_free(kitchen):
    """C-11: measured work presented as costing nothing.

    A zero here would say "this kitchen costs nothing to fit out", which is
    exactly the failure the platform exists to stop.
    """
    model, room, params = kitchen
    model.kitchen_platforms.clear()
    for rule in ("kitchen_platform", "service_platform",
                 "dado_above_platform", "dado_below_platform"):
        with pytest.raises(MissingKitchenPlatformError) as raised:
            QTY_RULES[rule](room, model, params)
        assert "not a free one" in str(raised.value) or \
               "not free" in str(raised.value) or \
               "costs nothing" in str(raised.value)


def test_the_wall_is_what_is_left_once_the_tiling_is_taken_off(kitchen):
    """You do not plaster behind the tiles.

    ``Internal Finishes Flats!E163 = (D158*D163)-(E161+E162)``.  Charging
    plaster over the dado as well counts the same square metre twice.
    """
    model, room, params = kitchen
    wall = QTY_RULES["wall_finish"](room, model, params, 3.1)
    bare = 10.0 * (3.1 - params["slab_allowance_m"])
    assert wall.value.value == pytest.approx(bare - 7.5 - 4.5)
    assert [i.name for i in wall.derivation.inputs][-2:] == [
        "less dado above the counter", "less dado below the counter"]
