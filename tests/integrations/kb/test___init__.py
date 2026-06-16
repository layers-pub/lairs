"""Unit tests for the lairs.integrations.kb package surface."""

from __future__ import annotations

from lairs.integrations import kb
from lairs.integrations.kb import Candidate, Edge, Entity


def test_exports() -> None:
    assert set(kb.__all__) == {"Candidate", "Edge", "Entity"}


def test_entity_construction() -> None:
    ent = Entity(ref="Q42", label="Douglas Adams")
    assert ent.ref == "Q42"
    assert ent.aliases == ()


def test_candidate_construction() -> None:
    cand = Candidate(ref="Q42", label="Douglas Adams", score=0.9)
    assert cand.score == 0.9


def test_edge_roundtrip() -> None:
    edge = Edge(source="Q42", relation="P106", target="Q36180")
    back = Edge.model_validate_json(edge.model_dump_json())
    assert back == edge
