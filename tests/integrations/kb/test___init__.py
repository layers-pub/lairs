"""Unit tests for the lairs.integrations.kb package surface."""

from __future__ import annotations

import importlib
import sys

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


def test_importing_kb_does_not_import_optional_libs() -> None:
    # importing the package or any connector module must never pull in the
    # optional heavy libraries; they are imported lazily on first use only.
    importlib.import_module("lairs.integrations.kb.glazing")
    importlib.import_module("lairs.integrations.kb.reconciliation")
    importlib.import_module("lairs.integrations.kb.wikidata")
    assert "glazing" not in sys.modules
    assert "qwikidata" not in sys.modules
    assert "SPARQLWrapper" not in sys.modules
