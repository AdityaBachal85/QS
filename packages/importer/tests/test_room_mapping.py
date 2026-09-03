"""Linking room names to the rate blocks that price them."""

import pytest

from qs_importer.mappers.room_mapping import propose_mappings, score


def test_the_two_vocabularies_are_bridged(model):
    """Only 6 of 25 room types match by name; the rest need a proposal."""
    proposals = propose_mappings(model)
    assert len(proposals) == 25
    assert all(p.target_id for p in proposals), \
        [p.room_type_name for p in proposals if not p.target_id]


@pytest.mark.parametrize("room,expected", [
    ("M. Bedroom", "M. Bed"),
    ("M. Toilet", "Toilet With M. Bed"),
    ("Balcony", "Balcony / Utility"),
    ("Multi Purpose Room", "Living, Dining & Passage"),
    ("Refugee", "Refuge Room"),
    ("WC", "Toilet"),
])
def test_the_proposals_are_the_ones_a_qs_would_make(model, room, expected):
    proposals = {p.room_type_name: p for p in propose_mappings(model)}
    assert proposals[room].target_name == expected


def test_a_proposal_is_never_treated_as_a_decision(model):
    """Getting one wrong prices a bedroom as a toilet, so each stays flagged."""
    guessed = [t for t in model.room_types
               if t.prices_as_id and not t.mapping_confirmed]
    assert guessed, "the import proposed links, and none is marked agreed"


def test_a_room_type_pricing_under_its_own_name_needs_no_confirmation(model):
    kitchen = next(t for t in model.room_types if t.name == "Kitchen")
    assert kitchen.prices_as_id is None
    assert kitchen.mapping_confirmed


def test_the_mapping_is_reported_in_the_import_notes(avs):
    assert any("pricing link" in w for w in avs.warnings)


def test_scoring_prefers_the_closer_name():
    assert score("M. Bedroom", "M. Bed") > score("M. Bedroom", "C. Bed")
    assert score("Kitchen", "Kitchen") == 1.0


def test_every_room_now_reaches_a_finish_schedule(model):
    without = [r.label for r in model.unit_type_rooms
               if not model.finish_spec_for(r.room_type_id)]
    assert len(without) < len(model.unit_type_rooms) * 0.1, without[:10]
