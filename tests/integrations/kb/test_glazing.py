"""Unit and integration tests for lairs.integrations.kb.glazing."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from lairs.integrations.kb import Candidate, Edge, Entity
from lairs.integrations.kb.glazing import (
    GlazingKB,
    GlazingNotInstalledError,
    _confidence_for,
)
from lairs.integrations.ports import KnowledgeBase

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.integrations.kb.glazing import XrefLinks


class _FakeHit:
    """A stand-in for a glazing unified-search hit."""

    def __init__(self, dataset: str, name: str, score: float) -> None:
        self.dataset = dataset
        self.name = name
        self.score = score


class _FakeSearch:
    """A stand-in for ``glazing.search.UnifiedSearch``."""

    def __init__(self, hits: Sequence[_FakeHit]) -> None:
        self._hits = hits
        self.calls = 0

    def search(self, query: str) -> Sequence[_FakeHit]:
        _ = query
        self.calls += 1
        return self._hits


class _FakeIndex:
    """A stand-in for ``glazing.references.index.CrossReferenceIndex``."""

    def __init__(self, links: XrefLinks) -> None:
        self._links = links
        self.calls: list[tuple[str, str]] = []

    def resolve(self, ref: str, *, source: str) -> XrefLinks:
        self.calls.append((ref, source))
        return self._links


def _kb_with_search(hits: Sequence[_FakeHit]) -> tuple[GlazingKB, _FakeSearch]:
    kb = GlazingKB()
    fake = _FakeSearch(hits)
    kb._search = fake  # inject the lazily-imported searcher
    return kb, fake


def _kb_with_index(links: XrefLinks) -> tuple[GlazingKB, _FakeIndex]:
    kb = GlazingKB()
    fake = _FakeIndex(links)
    kb._xref = fake  # inject the lazily-imported index
    return kb, fake


def test_name() -> None:
    assert GlazingKB.name == "glazing"


def test_conforms_to_port() -> None:
    assert isinstance(GlazingKB(), KnowledgeBase)


def test_resolve_without_glazing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # simulate glazing being absent so the error path runs regardless of install.
    monkeypatch.setitem(sys.modules, "glazing", None)
    with pytest.raises(GlazingNotInstalledError, match="lairs\\[lexical\\]"):
        GlazingKB().resolve("give.01")


def test_search_without_glazing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "glazing", None)
    with pytest.raises(GlazingNotInstalledError):
        GlazingKB().search("give")


def test_neighbors_without_glazing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "glazing", None)
    with pytest.raises(GlazingNotInstalledError):
        GlazingKB().neighbors("give.01")


def test_not_installed_error_is_import_error() -> None:
    assert issubclass(GlazingNotInstalledError, ImportError)


def test_search_maps_hits_to_candidates() -> None:
    kb, _fake = _kb_with_search(
        [_FakeHit("propbank", "give.01", 0.9), _FakeHit("verbnet", "give-13.1", 0.7)],
    )
    candidates = kb.search("give")
    assert all(isinstance(candidate, Candidate) for candidate in candidates)
    assert candidates[0] == Candidate(
        ref="propbank:give.01", label="give.01", score=0.9
    )
    assert candidates[1].ref == "verbnet:give-13.1"


def test_search_filters_by_resource_type() -> None:
    kb, _fake = _kb_with_search(
        [_FakeHit("propbank", "give.01", 0.9), _FakeHit("verbnet", "give-13.1", 0.7)],
    )
    candidates = kb.search("give", types=["verbnet"])
    assert [candidate.ref for candidate in candidates] == ["verbnet:give-13.1"]


def test_search_is_cached() -> None:
    kb, fake = _kb_with_search([_FakeHit("propbank", "give.01", 0.9)])
    kb.search("give")
    kb.search("give")
    assert fake.calls == 1


def test_resolve_maps_cross_references_to_same_as() -> None:
    kb, fake = _kb_with_index(
        {"verbnet_classes": ["give-13.1"], "framenet_frames": ["Giving"]},
    )
    entity = kb.resolve("propbank:give.01")
    assert isinstance(entity, Entity)
    assert entity.ref == "propbank:give.01"
    assert entity.types == ("propbank",)
    assert "verbnet_classes:give-13.1" in entity.same_as
    assert "framenet_frames:Giving" in entity.same_as
    assert fake.calls == [("give.01", "propbank")]


def test_resolve_defaults_bare_id_to_propbank() -> None:
    kb, fake = _kb_with_index({"verbnet_classes": ["give-13.1"]})
    kb.resolve("give.01")
    assert fake.calls == [("give.01", "propbank")]


def test_resolve_is_cached() -> None:
    kb, fake = _kb_with_index({"verbnet_classes": ["give-13.1"]})
    kb.resolve("propbank:give.01")
    kb.resolve("propbank:give.01")
    assert len(fake.calls) == 1


def test_neighbors_maps_links_to_edges() -> None:
    kb, _fake = _kb_with_index({"verbnet_classes": ["give-13.1", "give-13.3"]})
    edges = kb.neighbors("propbank:give.01")
    assert all(isinstance(edge, Edge) for edge in edges)
    assert (
        Edge(
            source="propbank:give.01",
            relation="verbnet_classes",
            target="give-13.1",
        )
        in edges
    )


def test_neighbors_folds_confidence_into_relation() -> None:
    kb, _fake = _kb_with_index(
        {
            "verbnet_classes": ["give-13.1"],
            "confidence_scores": {"verbnet_classes": {"give-13.1": 0.85}},
        },
    )
    edges = kb.neighbors("propbank:give.01")
    assert edges == [
        Edge(
            source="propbank:give.01",
            relation="verbnet_classes@0.85",
            target="give-13.1",
        ),
    ]


def test_neighbors_honours_rel_filter() -> None:
    kb, _fake = _kb_with_index(
        {"verbnet_classes": ["give-13.1"], "framenet_frames": ["Giving"]},
    )
    edges = kb.neighbors("propbank:give.01", rels=["framenet_frames"])
    assert [edge.target for edge in edges] == ["Giving"]


def test_confidence_for_defaults_to_one() -> None:
    links: XrefLinks = {"verbnet_classes": ["x"]}
    assert _confidence_for(links, "verbnet_classes", "x") == 1.0


def test_confidence_for_reads_nested_score() -> None:
    links: XrefLinks = {
        "verbnet_classes": ["x"],
        "confidence_scores": {"verbnet_classes": {"x": 0.5}},
    }
    assert _confidence_for(links, "verbnet_classes", "x") == 0.5


@pytest.mark.integration
def test_resolve_live() -> None:
    pytest.importorskip("glazing")
    pytest.skip("requires glazing data downloaded via `glazing init`")
