"""Unit and integration tests for lairs.integrations.kb.wikidata."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.integrations.kb import Candidate, Edge, Entity
from lairs.integrations.kb.wikidata import WikidataKB, _qid
from lairs.integrations.ports import KnowledgeBase

if TYPE_CHECKING:
    from collections.abc import Callable

_ENTITY_DATA = {
    "entities": {
        "Q42": {
            "labels": {"en": {"language": "en", "value": "Douglas Adams"}},
            "descriptions": {
                "en": {"language": "en", "value": "English writer and humorist"},
            },
            "aliases": {
                "en": [
                    {"language": "en", "value": "Douglas Noel Adams"},
                    {"language": "en", "value": "Douglas Noël Adams"},
                ],
            },
            "claims": {
                "P31": [
                    {
                        "mainsnak": {
                            "datavalue": {"value": {"id": "Q5"}},
                        },
                    },
                ],
            },
            "sitelinks": {
                "enwiki": {"url": "https://en.wikipedia.org/wiki/Douglas_Adams"},
            },
        },
    },
}

_SEARCH_RESPONSE = {
    "search": [
        {"id": "Q42", "label": "Douglas Adams"},
        {"id": "Q5", "label": "human"},
    ],
}

_SPARQL_RESPONSE = {
    "results": {
        "bindings": [
            {
                "p": {"value": "http://www.wikidata.org/prop/direct/P31"},
                "o": {"value": "http://www.wikidata.org/entity/Q5"},
            },
        ],
    },
}


def _kb(handler: Callable[[httpx.Request], httpx.Response]) -> WikidataKB:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return WikidataKB(client=client)


def test_name() -> None:
    assert WikidataKB.name == "wikidata"


def test_conforms_to_port() -> None:
    assert isinstance(WikidataKB(), KnowledgeBase)


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("Q42", "Q42"),
        ("wd:Q42", "Q42"),
        ("http://www.wikidata.org/entity/Q42", "Q42"),
    ],
)
def test_qid_normalisation(ref: str, expected: str) -> None:
    assert _qid(ref) == expected


def test_resolve_parses_entity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Q42.json")
        return httpx.Response(200, json=_ENTITY_DATA)

    with _kb(handler) as kb:
        entity = kb.resolve("Q42")
    assert isinstance(entity, Entity)
    assert entity.label == "Douglas Adams"
    assert entity.description == "English writer and humorist"
    assert entity.aliases == ("Douglas Noel Adams", "Douglas Noël Adams")
    assert entity.types == ("Q5",)
    assert entity.same_as == ("https://en.wikipedia.org/wiki/Douglas_Adams",)


def test_resolve_accepts_uri() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ENTITY_DATA)

    with _kb(handler) as kb:
        entity = kb.resolve("http://www.wikidata.org/entity/Q42")
    assert entity.ref == "Q42"


def test_resolve_is_cached() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_ENTITY_DATA)

    with _kb(handler) as kb:
        kb.resolve("Q42")
        kb.resolve("Q42")
    assert calls["n"] == 1


def test_search_ranks_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["action"] == "wbsearchentities"
        return httpx.Response(200, json=_SEARCH_RESPONSE)

    with _kb(handler) as kb:
        candidates = kb.search("Adams")
    assert all(isinstance(candidate, Candidate) for candidate in candidates)
    assert candidates[0].ref == "Q42"
    # ranks decrease monotonically with position.
    assert candidates[0].score > candidates[1].score


def test_search_is_cached() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_SEARCH_RESPONSE)

    with _kb(handler) as kb:
        kb.search("Adams")
        kb.search("Adams")
    assert calls["n"] == 1


def test_neighbors_parses_sparql() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "query" in request.url.params
        return httpx.Response(200, json=_SPARQL_RESPONSE)

    with _kb(handler) as kb:
        edges = kb.neighbors("Q42")
    assert edges == [Edge(source="Q42", relation="P31", target="Q5")]


def test_neighbors_rel_filter_in_query() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params["query"]
        return httpx.Response(200, json=_SPARQL_RESPONSE)

    with _kb(handler) as kb:
        kb.neighbors("Q42", rels=["P31"])
    assert "wdt:P31" in captured["query"]


@pytest.mark.integration
def test_resolve_live() -> None:
    pytest.skip("requires network access to the Wikidata endpoints")
