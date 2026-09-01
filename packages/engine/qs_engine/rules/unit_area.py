"""Unit and room areas, derived.

``area_sqft`` is a function, not a field.  Everything downstream -- room total,
unit-type subtotal, type total across all units -- is computed from the sq.m
input and the conversion parameter, so there is no stored square-foot value
anywhere for a stray paste to land in (C-3).
"""

from __future__ import annotations

from ..model import ProjectModel, UnitTypeRoom
from ..params import ParameterSet
from ..provenance import Derived, Input, derive


def room_area_sqft(room: UnitTypeRoom, params: ParameterSet) -> Derived:
    factor = params["factor_sqm_to_sqft"]
    return derive(room.carpet_area_sqm * factor, "sqm_to_sqft",
                  f"{room.carpet_area_sqm:g} x {factor:g}",
                  [Input("carpet_area_sqm", room.carpet_area_sqm),
                   Input("factor_sqm_to_sqft", factor, "parameter")],
                  excel_ref="Flat Sizes!E5 = D5*10.764")


def room_total_sqft(room: UnitTypeRoom, params: ParameterSet) -> Derived:
    """Room area x how many of that room the unit has."""
    each = room_area_sqft(room, params)
    total = each.value * room.count_per_unit
    return derive(total, "room_total", f"{each.value:,.4f} x {room.count_per_unit:g}",
                  [Input("area_sqft", each.value), Input("count_per_unit", room.count_per_unit)],
                  excel_ref="Flat Sizes!F12 = E12*C12")


def unit_type_area_sqft(unit_type_id: str, model: ProjectModel,
                        params: ParameterSet) -> Derived:
    """Carpet area of one unit of this type.

    A fold over however many rooms the type has -- five or ten or four
    bathrooms' worth -- not ``SUM(F12:F19)`` over a fixed range.
    """
    rooms = model.rooms_of(unit_type_id)
    total = sum(room_total_sqft(r, params).value for r in rooms)
    return derive(total, "unit_type_area", f"sum over {len(rooms)} room(s)",
                  [Input(r.label, room_total_sqft(r, params).value) for r in rooms],
                  excel_ref="Flat Sizes!F20 = SUM(F12:F19)")


def unit_type_area_sqm(unit_type_id: str, model: ProjectModel) -> Derived:
    rooms = model.rooms_of(unit_type_id)
    total = sum(r.carpet_area_sqm * r.count_per_unit for r in rooms)
    return derive(total, "unit_type_area_sqm", f"sum over {len(rooms)} room(s)",
                  [Input(r.label, r.carpet_area_sqm) for r in rooms])


def unit_type_total_sqft(unit_type_id: str, model: ProjectModel,
                         params: ParameterSet) -> Derived:
    """Area of one unit x the number of units of that type in the building."""
    each = unit_type_area_sqft(unit_type_id, model, params)
    count = model.unit_count(unit_type_id)
    return derive(each.value * count, "unit_type_total",
                  f"{each.value:,.4f} x {count}",
                  [Input("area_per_unit_sqft", each.value),
                   Input("unit_count", count, "sum of floor_unit_mix")],
                  excel_ref="Flat Sizes!I11 = +H11*F20")
