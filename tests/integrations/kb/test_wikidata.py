"""Unit and integration tests for lairs.integrations.kb.wikidata."""

from __future__ import annotations

import pytest

from lairs.integrations.kb.wikidata import WikidataKB


def test_name() -> None:
    assert WikidataKB.name == "wikidata"


def test_resolve_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        WikidataKB().resolve("ref")


def test_search_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        WikidataKB().search("text")


def test_neighbors_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        WikidataKB().neighbors("ref")


@pytest.mark.integration
def test_resolve_live() -> None:
    pytest.importorskip("qwikidata")
    pytest.skip("requires network access or a local dump")
