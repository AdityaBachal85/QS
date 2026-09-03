"""The whole import, in one call.

Stage 1 Extract -> Stage 2 Map -> Stage 3 Flag.  Nothing is auto-corrected:
defects are imported as they stand, reported, and changed only when somebody
approves the change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from qs_engine.model import ProjectModel
from qs_engine.params import ParameterSet

from .ids import IdFactory
from .mappers.cost_lines import map_cost_lines
from .mappers.openings import map_openings
from .mappers.rates import SHEET_FLATS, SHEET_OFFICE, map_rate_list
from .mappers.room_conf import map_room_conf, new_model
from .mappers.room_mapping import apply_proposals, propose_mappings
from .mappers.unit_sizes import map_common_areas, map_unit_sizes
from .reader import Workbook


@dataclass
class ImportResult:
    model: ProjectModel
    params: ParameterSet
    workbook: Workbook
    warnings: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        m = self.model
        return {
            "floors": len(m.floors), "unit types": len(m.unit_types),
            "floor mix rows": len(m.floor_unit_mix), "room types": len(m.room_types),
            "rooms": len(m.unit_type_rooms), "opening types": len(m.opening_types),
            "room openings": len(m.room_openings), "rate items": len(m.rate_items),
            "finish slots": len(m.finish_slots),
            "finish specs": len(m.room_finish_specs),
            "cost sections": len(m.cost_sections),
            "cost lines": len(m.cost_lines),
        }


def import_workbook(path: str | Path, *, params: ParameterSet | None = None) -> ImportResult:
    """Read the AVS-layout workbook into a project model."""
    wb = Workbook(path)
    ids = IdFactory()
    model = map_room_conf(wb, new_model(), ids)
    map_unit_sizes(wb, model, ids)
    map_unit_sizes(wb, model, ids, sheet="Office Sizes", first_row=4, last_row=43)
    map_common_areas(wb, model, ids)
    warnings = list(map_openings(wb, model, ids))
    warnings += map_rate_list(wb, model, ids, sheet=SHEET_FLATS)
    warnings += map_rate_list(wb, model, ids, sheet=SHEET_OFFICE, last_row=400)
    # Link the sizes sheets' room names to the rate blocks that price them.
    # Proposed, never decided: each link stays unconfirmed until a QS agrees.
    warnings += apply_proposals(model, propose_mappings(model))
    # Infra, Amenities and Preliminary -- Rs 9.66 Cr the platform
    # has never seen, in the same Description/Unit/Qty/Rate shape.
    warnings += map_cost_lines(wb, model, ids)
    return ImportResult(model, params or ParameterSet.defaults(), wb, warnings)
