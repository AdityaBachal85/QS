"""The domain model.

Two rules govern everything here:

1. **Identity, never position.**  Every reference is by a stable id.  The
   workbook's take-off reaches its rates by row offset -- ``Internal Finishes
   Flats!B5 = 'Rate List - Flats'!B6``, repeated across ~150 blocks with
   hand-counted offsets -- so inserting one row in the rate list silently
   re-prices the building (C-6).  Nothing here can move because a row moved.

2. **Shape is data, never schema.**  A unit type owns as many rooms as it has.
   Four bathrooms is four rows; no balcony is no row; a room type this codebase
   has never heard of is a row someone added.  Nothing counts rooms, assumes a
   maximum, or hard-codes AVS's fifteen flat types.

Derived values are absent by design.  ``area_sqft`` is not a field, because a
field can be overwritten -- which is precisely how ``Flat Sizes!E57`` came to
hold 7.01, a perimeter pasted into an area column, understating Flat 3B across
27 units (C-3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence


class FloorType(Enum):
    BASEMENT = "basement"
    GROUND = "ground"
    PODIUM = "podium"
    TYPICAL = "typical"
    REFUGE = "refuge"
    TERRACE = "terrace"
    LMR = "lmr"


class RoomCategory(Enum):
    """What kind of space a room is.

    This drives which finishes apply -- a toilet has dado, a bedroom does not --
    so it is a closed set.  The open set is ``RoomType``: users add "Powder
    Room" or "Servant Toilet" freely, and assign it a category.
    """

    HABITABLE = "habitable"
    TOILET = "toilet"
    KITCHEN = "kitchen"
    UTILITY = "utility"
    BALCONY = "balcony"
    CIRCULATION = "circulation"
    SERVICE = "service"
    OTHER = "other"


class OpeningKind(Enum):
    DOOR = "door"
    WINDOW = "window"
    RAILING = "railing"
    CURTAIN_WALL = "curtain_wall"
    VENTILATOR = "ventilator"


class BuildupMethod(Enum):
    """How an overall rate is built from its components.

    These eight cover every distinct formula shape in ``Rate List - Flats``
    rows 4-300.  The 1.1, 10.764, 3.28 and 0.1 that were typed into those
    formulas become named parameters.
    """

    AREA_WITH_WASTAGE = "area_with_wastage"
    AREA_SIMPLE = "area_simple"
    LINEAR_WITH_WASTAGE = "linear_with_wastage"
    FRAME = "frame"
    AREA_SUM = "area_sum"
    PASSTHROUGH = "passthrough"
    LINK = "link"
    CONSTANT = "constant"


class LineStatus(Enum):
    """A line is never removed by arithmetic.

    ``Electrical!G4 = G104*0`` computes Rs 1,98,22,055 in full and then
    multiplies it by zero, so it reaches no report and no reviewer can see it
    (C-2).  An excluded line here keeps its value, carries a reason, and is
    reported separately.
    """

    ACTIVE = "active"
    EXCLUDED = "excluded"
    PROVISIONAL = "provisional"


# --------------------------------------------------------------------------
# Project and structure
# --------------------------------------------------------------------------

@dataclass
class Project:
    id: str
    code: str
    name: str
    city: str = ""
    client: str = ""


@dataclass
class Building:
    id: str
    project_id: str
    name: str
    building_type: str = "tower"


@dataclass
class Floor:
    """One floor.  ``seq`` orders them; nothing depends on row position."""

    id: str
    building_id: str
    seq: int
    name: str
    floor_to_floor_ht: float
    floor_type: FloorType = FloorType.TYPICAL


@dataclass
class UnitType:
    """A flat type, office type or common-area type.

    ``classification`` is free text ("1BHK", "3BHK", "Office", "Shop",
    "Penthouse") and is an *attribute*, which is what kills C-21: the workbook
    computes its BHK split from hand-typed column lists --
    ``Room Conf!L44 = M40+O40+R40+U40+V40+Y40+Z40+P40``, with ``P40`` appended
    out of sequence, evidence of a later patch.  Here the split is a group-by
    and cannot go stale when a type is added.
    """

    id: str
    project_id: str
    code: str
    classification: str = ""
    is_residential: bool = True
    is_common_area: bool = False
    seq: int = 0
    #: Set only for entities whose count does not come from the floor matrix --
    #: service cores, refuge areas, and anything the workbook typed straight
    #: into a schedule (``Doors!K137`` = 37 with no formula behind it).  Kept
    #: because dropping it would lose openings, flagged because a count that
    #: is not derived from the building cannot be checked against it.
    count_override: int | None = None


@dataclass
class FloorUnitMix:
    """How many of one unit type sit on one floor.  Replaces the Room Conf matrix."""

    id: str
    floor_id: str
    unit_type_id: str
    count: int


# --------------------------------------------------------------------------
# Rooms
# --------------------------------------------------------------------------

@dataclass
class RoomType:
    """Open master data -- users add room types without a release.

    ``prices_as_id`` exists because the workbook keeps two vocabularies for the
    same rooms.  ``Flat Sizes`` says ``M. Bedroom``; ``Rate List - Flats`` calls
    the block that prices it ``M. Bed``.  ``M. Toilet`` is priced by a block
    named ``Toilet With M. Bed``, and ``Balcony`` by ``Balcony / Utility``.  Only
    6 of 25 room types match by name, so without this link 98 of 154 rooms can
    be measured and not priced.

    The importer *proposes* these links; ``mapping_confirmed`` stays False until
    a QS agrees, and every unconfirmed link is reported by the validation engine
    with the proposal named. The money is visible immediately, and so is the
    fact that a guess is holding it up.
    """

    id: str
    project_id: str
    name: str
    category: RoomCategory = RoomCategory.HABITABLE
    #: The room type whose finish schedule prices this one. None = its own.
    prices_as_id: str | None = None
    #: False while the link above is still the importer's proposal.
    mapping_confirmed: bool = False


@dataclass
class UnitTypeRoom:
    """One room within a unit type.

    ``label`` distinguishes repeats: a flat with four bathrooms has four rows,
    all ``RoomCategory.TOILET``, labelled "M. Toilet", "C. Toilet", "Toilet 3",
    "Powder Room".  ``area_sqft`` is deliberately not a field.
    """

    id: str
    unit_type_id: str
    room_type_id: str
    seq: int
    label: str = ""
    count_per_unit: float = 1.0
    carpet_area_sqm: float = 0.0
    perimeter_m: float = 0.0
    clear_height_m: float | None = None
    dado_height_m: float | None = None


# --------------------------------------------------------------------------
# Finish schedule -- the generalisation of the Rate List block structure
# --------------------------------------------------------------------------

@dataclass
class FinishSlot:
    """One row of the per-room finish schedule (Flooring, Skirting, Dado, ...)."""

    id: str
    code: str
    name: str
    unit: str
    qty_rule: str
    seq: int = 0


@dataclass
class RoomFinishSpec:
    """Which finish applies to which room type, at which rate.

    A toilet has dado and a bedroom does not because ``is_applicable`` says so,
    not because code says so.
    """

    id: str
    project_id: str
    room_type_id: str
    finish_slot_id: str
    rate_item_id: str | None = None
    qty_rule: str | None = None
    is_applicable: bool = True
    notes: str = ""


# --------------------------------------------------------------------------
# Openings
# --------------------------------------------------------------------------

@dataclass
class OpeningType:
    """A door, window, railing or curtain-wall type.

    ``area_sqm`` is derived from width x height, never stored.  There is no row
    limit here, which removes C-18: the workbook's cost sheet VLOOKUPs are
    bounded to ``Doors!D146:H149`` (4 types) and ``Windows!D166:H177`` (12), so
    a fifth door type yields ``#N/A`` or a silent omission.
    """

    id: str
    project_id: str
    code: str
    kind: OpeningKind
    width_m: float = 0.0
    height_m: float = 0.0
    rate_item_id: str | None = None
    specification: str = ""

    @property
    def area_sqm(self) -> float:
        return self.width_m * self.height_m


@dataclass
class RoomOpening:
    """An opening placed in a room.

    Openings attach to rooms, which is what lets a deduction be a rule over the
    room's actual openings instead of ``-(Doors!H5+Doors!H6+Doors!H7+Doors!H9)``
    -- a hand-picked cell list written ~150 times, from which ``Doors!H8`` is
    silently absent with no record of whether that was deliberate (C-13).
    """

    id: str
    unit_type_room_id: str
    opening_type_id: str
    count: float = 1.0
    #: Set when an opening sits in this room's wall but serves another room --
    #: the bedroom door that interrupts the living room's skirting.
    serves_room_id: str | None = None
    #: Explicit run in metres, for openings whose quantity is a length rather
    #: than width x height. Balcony and utility railings are measured this way:
    #: ``Windows!K156 = 1.37+2.13`` is a typed run, and ``D&W Schedule!B20``
    #: ("BR/UR") carries a rate but no dimensions at all.
    linear_qty_m: float | None = None


# --------------------------------------------------------------------------
# Rates
# --------------------------------------------------------------------------

@dataclass
class RateItem:
    """The stable identity of a priced item.  Referenced by take-off lines."""

    id: str
    project_id: str | None
    code: str
    description: str
    unit: str
    category: str = ""
    specification: str = ""
    is_active: bool = True


@dataclass
class RateRevision:
    """A price for a rate item at a point in time.

    ``overall_rate`` is computed by :mod:`qs_engine.rules.rate_buildup`, never
    typed.  Two live rates for the same work -- shuttering at Rs 900 on the
    Shuttering Summary and Rs 1,086 on the Cost Sheet, Rs 1.25 Cr apart (C-7) --
    become one rate plus one dated revision with a reason.
    """

    id: str
    rate_item_id: str
    method: BuildupMethod
    basic_rate: float | None = None
    laying_rate: float | None = None
    wastage_pct: float | None = None
    #: For LINK: the rate item this one mirrors.  Makes the C-32 daisy chain
    #: (``E20 = E6``, ``E34 = E20``, but ``E23 = $E$9``) explicit and traceable.
    links_to_rate_item_id: str | None = None
    constant_value: float | None = None
    #: Frame width for the FRAME method.  Mostly 0.1 m, but ``G102`` uses 2.2 --
    #: a different profile, written into the formula with nothing naming it.
    frame_width_m: float | None = None
    #: Applied to PASSTHROUGH / AREA_SUM results.  ``Rate List - Flats!G245``
    #: is ``(E245+F245)*1.03`` and ``G238`` is ``(E238+F238)-250`` -- a factor
    #: and a rebate written into the formula text with nothing saying what
    #: either represents.
    adjustment_factor: float = 1.0
    adjustment_constant: float = 0.0
    revision_no: int = 1
    effective_from: str = ""
    approved_by: str = ""
    source: str = ""
    supersedes_id: str | None = None

    @property
    def is_priced(self) -> bool:
        """False when the revision carries no price components at all.

        A rate row with a formula and empty inputs computes to zero and looks
        exactly like a genuine zero.  ``Cost Sheet Tower!I99`` is False Ceiling
        for the common lobby: 4,508.24 sq.m of measured quantity at a rate of
        nothing, showing Rs 0 -- while the cell beside it, ``L99``, works out
        what it should cost at Rs 135/sq.ft and reaches no total (C-11).  That
        is Rs 65.5 lakh of known work presented as zero.  Here it is a blocking
        MISSING_RATE.
        """
        return any(v is not None for v in
                   (self.basic_rate, self.laying_rate, self.constant_value))


@dataclass
class ProjectRate:
    """A project-level override of a library rate, with a reason and an approver."""

    id: str
    project_id: str
    rate_item_id: str
    rate_revision_id: str | None = None
    override_value: float | None = None
    override_reason: str = ""
    override_approved_by: str = ""


@dataclass(frozen=True)
class HeightPlacement:
    """A unit type's presence on floors that share one floor-to-floor height.

    Wall, dado and any other height-driven quantity differ between a unit on the
    Ground Floor (4.2 m) and the same unit on a typical floor (3.1 m).  Fifteen
    of AVS's thirty-five unit types sit on floors of more than one height --
    every Office spans 2.9 and 4.2, and the Staircase spans all six -- so a unit
    type does not have *a* height.  It has these.

    ``height_m`` is None when the placement carries no floor to take a height
    from, which is the case for entities counted by ``count_override``.
    """

    height_m: float | None
    count: int
    floors: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# Cost lines -- Infra, Amenities, Preliminary, and the cost sheets
# --------------------------------------------------------------------------

@dataclass
class CostSection:
    """One band of the project estimate: Preliminaries, Civil, MEP, Amenities.

    A section is a filter, not a range.  ``Summary!D11`` is
    ``SUM('Cost Sheet Tower'!I118:I125)`` and the MEP EXTERNAL band runs to row
    126, so the Substation at Rs 24,00,000 sits one row outside the total that
    is supposed to contain it and reaches the project budget through nothing
    (C-38).  A line belongs to a section because it says so, and no range can
    stop one row short.
    """

    id: str
    project_id: str
    code: str
    name: str
    seq: int = 0
    #: The workbook cell this section is reconciled against.
    excel_ref: str = ""


@dataclass
class CostLine:
    """One priced line of a cost sheet.

    ``amount`` is deliberately absent: it is qty x rate, computed.
    ``Infra!E5`` and ``E12`` are typed amounts sitting in a column where every
    neighbour is a formula, which is the C-33 shape -- here the lump sum
    becomes ``1 LS x Rs 15,00,000`` and the arithmetic is visible.

    A heading is a line with no rate whose amount is the fold of its children,
    so Amenities' seven groups keep their structure without storing a subtotal.
    """

    id: str
    project_id: str
    section_id: str
    seq: int
    description: str
    unit: str = ""
    qty: float | None = None
    rate_item_id: str | None = None
    manual_rate: float | None = None
    #: Set when this line groups others beneath it.
    parent_id: str | None = None
    status: LineStatus = LineStatus.ACTIVE
    #: Required when status is EXCLUDED. Nothing is removed by arithmetic (C-2).
    exclusion_reason: str = ""
    #: Where the figure came from, when it was carried rather than derived.
    source_ref: str = ""
    #: True when the quantity came from a sheet this platform has not modelled.
    qty_carried: bool = False

    @property
    def is_heading(self) -> bool:
        return self.rate_item_id is None and self.manual_rate is None and self.qty is None


@dataclass
class CostLineQty:
    """A component of a cost line's quantity.

    ``Infra!C9`` is ``=K10``, and K10 is 60% of three areas summed in a corner
    of the sheet -- a take-off hidden in a side calculation.  Here the
    components are rows, and the 60% is a parameter rather than a number typed
    into a formula.
    """

    id: str
    cost_line_id: str
    label: str
    value: float
    #: Names a project parameter holding the share; falls back to ``factor``.
    factor_param_key: str = ""
    factor: float = 1.0


# --------------------------------------------------------------------------
# The aggregate root
# --------------------------------------------------------------------------

@dataclass
class ProjectModel:
    """Everything the engine needs for one project revision, in memory.

    Deliberately a plain container: the engine takes this in and returns
    computed values plus provenance out, with no database and no web framework
    anywhere near it.  That is what lets every rule carry a test that runs in
    milliseconds against the workbook's own numbers.
    """

    project: Project
    buildings: list[Building] = field(default_factory=list)
    floors: list[Floor] = field(default_factory=list)
    unit_types: list[UnitType] = field(default_factory=list)
    floor_unit_mix: list[FloorUnitMix] = field(default_factory=list)
    room_types: list[RoomType] = field(default_factory=list)
    unit_type_rooms: list[UnitTypeRoom] = field(default_factory=list)
    finish_slots: list[FinishSlot] = field(default_factory=list)
    room_finish_specs: list[RoomFinishSpec] = field(default_factory=list)
    opening_types: list[OpeningType] = field(default_factory=list)
    room_openings: list[RoomOpening] = field(default_factory=list)
    rate_items: list[RateItem] = field(default_factory=list)
    rate_revisions: list[RateRevision] = field(default_factory=list)
    project_rates: list[ProjectRate] = field(default_factory=list)
    cost_sections: list[CostSection] = field(default_factory=list)
    cost_lines: list[CostLine] = field(default_factory=list)
    cost_line_qtys: list[CostLineQty] = field(default_factory=list)

    # -- lookups by id -----------------------------------------------------

    def unit_type(self, unit_type_id: str) -> UnitType:
        return _one(self.unit_types, unit_type_id, "unit type")

    def floor(self, floor_id: str) -> Floor:
        return _one(self.floors, floor_id, "floor")

    def room_type(self, room_type_id: str) -> RoomType:
        return _one(self.room_types, room_type_id, "room type")

    def room(self, room_id: str) -> UnitTypeRoom:
        return _one(self.unit_type_rooms, room_id, "room")

    def opening_type(self, opening_type_id: str) -> OpeningType:
        return _one(self.opening_types, opening_type_id, "opening type")

    def rate_item(self, rate_item_id: str) -> RateItem:
        return _one(self.rate_items, rate_item_id, "rate item")

    # -- relationships -----------------------------------------------------

    def rooms_of(self, unit_type_id: str) -> list[UnitTypeRoom]:
        """Every room in a unit type, in sequence.  Any number, any mix."""
        return sorted(
            (r for r in self.unit_type_rooms if r.unit_type_id == unit_type_id),
            key=lambda r: r.seq,
        )

    def openings_of(self, room_id: str) -> list[RoomOpening]:
        return [o for o in self.room_openings if o.unit_type_room_id == room_id]

    def revisions_of(self, rate_item_id: str) -> list[RateRevision]:
        return sorted(
            (r for r in self.rate_revisions if r.rate_item_id == rate_item_id),
            key=lambda r: r.revision_no,
        )

    def current_revision(self, rate_item_id: str) -> RateRevision | None:
        revisions = self.revisions_of(rate_item_id)
        return revisions[-1] if revisions else None

    def unit_count(self, unit_type_id: str) -> int:
        """How many units of this type exist, across every floor.

        A group-by, not ``SUM(L40:Z40)``.  A unit type added tomorrow is counted
        because it matches the filter, not because someone widened a range.
        """
        for ut in self.unit_types:
            if ut.id == unit_type_id and ut.count_override is not None:
                return ut.count_override
        return sum(m.count for m in self.floor_unit_mix if m.unit_type_id == unit_type_id)

    def height_placements(self, unit_type_id: str) -> list["HeightPlacement"]:
        """Where this unit type sits, grouped by floor-to-floor height.

        Grouped rather than listed per floor: a type on twenty-nine floors of
        3.1 m is one placement of twenty-nine, not twenty-nine placements.  The
        counts always sum to ``unit_count``, so folding over these can never
        change how many units the building has -- only how tall their walls are.
        """
        for ut in self.unit_types:
            if ut.id == unit_type_id and ut.count_override is not None:
                return [HeightPlacement(None, ut.count_override, ())]

        floors = {f.id: f for f in self.floors}
        grouped: dict[float, tuple[int, list[str]]] = {}
        for mix in self.floor_unit_mix:
            if mix.unit_type_id != unit_type_id or not mix.count:
                continue
            floor = floors.get(mix.floor_id)
            if floor is None:
                continue
            count, names = grouped.get(floor.floor_to_floor_ht, (0, []))
            grouped[floor.floor_to_floor_ht] = (count + mix.count, names + [floor.name])
        if not grouped:
            return []
        return [HeightPlacement(height, count, tuple(names))
                for height, (count, names) in sorted(grouped.items())]

    def counts_by_classification(self) -> dict[str, int]:
        """The BHK split, derived.  Replaces Room Conf's hand-typed column lists."""
        totals: dict[str, int] = {}
        for ut in self.unit_types:
            if ut.is_common_area:
                continue
            n = self.unit_count(ut.id)
            if n:
                totals[ut.classification] = totals.get(ut.classification, 0) + n
        return totals

    def lines_of(self, section_id: str) -> list["CostLine"]:
        return sorted((l for l in self.cost_lines if l.section_id == section_id),
                      key=lambda l: l.seq)

    def children_of(self, cost_line_id: str) -> list["CostLine"]:
        return sorted((l for l in self.cost_lines if l.parent_id == cost_line_id),
                      key=lambda l: l.seq)

    def qty_components(self, cost_line_id: str) -> list["CostLineQty"]:
        return [q for q in self.cost_line_qtys if q.cost_line_id == cost_line_id]

    def pricing_room_type(self, room_type_id: str) -> str:
        """Which room type's finish schedule prices this one.

        Follows ``prices_as_id`` one step, then stops -- a chain of links is how
        the workbook's rate daisy chain (C-32) went wrong, so this deliberately
        does not recurse.
        """
        room_type = self.room_type(room_type_id)
        return room_type.prices_as_id or room_type_id

    def finish_spec_for(self, room_type_id: str) -> list[RoomFinishSpec]:
        target = self.pricing_room_type(room_type_id)
        by_slot = {s.id: s for s in self.finish_slots}
        specs = [
            s for s in self.room_finish_specs
            if s.room_type_id == target and s.is_applicable
        ]
        return sorted(specs, key=lambda s: by_slot[s.finish_slot_id].seq
                      if s.finish_slot_id in by_slot else 0)


def _one(items: Sequence, item_id: str, what: str):
    for item in items:
        if item.id == item_id:
            return item
    raise KeyError(f"no {what} with id {item_id!r}")
