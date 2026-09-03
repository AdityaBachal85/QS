"""Linking the room names in the sizes sheets to the blocks that price them.

The workbook keeps two vocabularies for the same rooms, and they overlap by six
names out of twenty-five:

===========================  ==================================
``Flat Sizes`` says          ``Rate List - Flats`` prices it as
===========================  ==================================
M. Bedroom                   M. Bed
C. Bedroom / C.Bedroom       C. Bed
M. Toilet                    Toilet With M. Bed
Balcony, Utility             Balcony / Utility
Multi Purpose Room           Living, Dining & Passage
Smoke Check Lobby 1 and 2    Smoke Check Lobby
===========================  ==================================

Nothing here decides anything.  It proposes a link, records how confident the
proposal is and why, and leaves ``mapping_confirmed`` False so the validation
engine keeps asking until a QS agrees.  Getting one of these wrong prices a
bedroom as a toilet, which is exactly the kind of plausible-looking error the
platform exists to stop -- so it is offered, never applied quietly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from qs_engine.model import ProjectModel, RoomCategory

#: Words that mean the same room. Checked after normalising, before scoring.
_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("bedroom", "bed"),
    ("wc", "toilet"),
    ("bathroom", "toilet"),
    ("multi purpose room", "living dining passage"),
    ("multipurpose room", "living dining passage"),
    ("living dining", "living dining passage"),
    ("lift", "lift shaft"),
    ("lobby", "lift lobby"),
    ("refugee", "refuge room"),
    ("electric duct", "electrical duct"),
    ("staircase", "staircase area"),
)

_NOISE = re.compile(r"\b(\d+|and|&|the|of|no|nos)\b")


def normalise(name: str) -> str:
    text = " ".join(str(name).split()).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = _NOISE.sub(" ", text)
    return " ".join(text.split())


def _tokens(name: str) -> set[str]:
    expanded = normalise(name)
    for a, b in _SYNONYMS:
        if a in expanded:
            expanded = f"{expanded} {b}"
    return set(expanded.split())


def score(a: str, b: str) -> float:
    """0 to 1. Exact after normalising is 1; otherwise token overlap."""
    if normalise(a) == normalise(b):
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def shared(a: str, b: str) -> int:
    """How many words two names actually have in common.

    Overlap alone ties too often: ``M. Toilet`` scores 0.5 against both
    ``Toilet`` and ``Toilet With M. Bed``. The second shares two words rather
    than one, which is more evidence for the same room, so it wins the tie.
    """
    return len(_tokens(a) & _tokens(b))


@dataclass(frozen=True)
class Proposal:
    room_type_id: str
    room_type_name: str
    target_id: str | None
    target_name: str
    confidence: float
    reason: str


def propose_mappings(model: ProjectModel,
                     threshold: float = 0.34) -> list[Proposal]:
    """For every room type that rooms actually use, find the block that prices it."""
    priced_ids = {s.room_type_id for s in model.room_finish_specs}
    priced = [model.room_type(i) for i in priced_ids if _exists(model, i)]
    used_ids = {r.room_type_id for r in model.unit_type_rooms}

    proposals: list[Proposal] = []
    for room_type_id in sorted(used_ids):
        room_type = model.room_type(room_type_id)
        if room_type_id in priced_ids:
            proposals.append(Proposal(
                room_type_id, room_type.name, room_type_id, room_type.name,
                1.0, "prices under its own name"))
            continue

        def rank(candidates):
            return sorted(
                ((score(room_type.name, c.name), shared(room_type.name, c.name), c)
                 for c in candidates),
                key=lambda t: (t[0], t[1]), reverse=True)

        ranked = rank([c for c in priced
                       if c.category is room_type.category
                       or c.category is RoomCategory.OTHER])
        # Fall back to ignoring category when nothing in the same one matches.
        if not ranked or ranked[0][0] < threshold:
            ranked = rank(priced)

        if ranked and ranked[0][0] >= threshold:
            best, _shared, candidate = ranked[0]
            proposals.append(Proposal(
                room_type_id, room_type.name, candidate.id, candidate.name,
                round(best, 2),
                f"closest name in the rate list ({int(best * 100)}% of words shared)"))
        else:
            proposals.append(Proposal(
                room_type_id, room_type.name, None, "",
                0.0, "no rate block resembles this room"))
    return proposals


def _exists(model: ProjectModel, room_type_id: str) -> bool:
    return any(t.id == room_type_id for t in model.room_types)


def apply_proposals(model: ProjectModel,
                    proposals: list[Proposal]) -> list[str]:
    """Record the proposals as unconfirmed links, and say what was proposed.

    The links are live, so quantities price immediately and a QS can see the
    money. They are also unconfirmed, so the validation engine keeps reporting
    each one until somebody agrees with it.
    """
    guessed = 0
    for proposal in proposals:
        room_type = model.room_type(proposal.room_type_id)
        if proposal.target_id == proposal.room_type_id:
            room_type.prices_as_id = None
            room_type.mapping_confirmed = True
            continue
        room_type.prices_as_id = proposal.target_id
        room_type.mapping_confirmed = False
        if proposal.target_id:
            guessed += 1

    unmatched = [p.room_type_name for p in proposals if p.target_id is None]
    notes = []
    if guessed:
        notes.append(
            f"Proposed a pricing link for {guessed} room type(s) whose names "
            f"differ between the sizes sheets and the rate list (M. Bedroom vs "
            f"M. Bed, and so on). Quantities price on these links now, and every "
            f"one is reported as unconfirmed until a QS agrees with it."
        )
    if unmatched:
        notes.append(
            f"{len(unmatched)} room type(s) resemble no rate block and cannot be "
            f"priced yet: {', '.join(sorted(unmatched)[:8])}"
            + ("…" if len(unmatched) > 8 else "")
        )
    return notes
