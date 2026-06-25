"""Unit and integration tests for lairs.integrations.kb.wikidata."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.integrations.kb import Candidate, Edge, Entity
from lairs.integrations.kb.wikidata import (
    DEFAULT_USER_AGENT,
    WikidataError,
    WikidataKB,
    _qid,
    _search_label,
)
from lairs.integrations.ports import KnowledgeBase

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from conftest import RouteHandler

    from lairs._types import JsonValue

_ENTITY_DATA: JsonValue = {
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

_SEARCH_RESPONSE: JsonValue = {
    "search": [
        {"id": "Q42", "label": "Douglas Adams"},
        {"id": "Q5", "label": "human"},
    ],
}

_SPARQL_RESPONSE: JsonValue = {
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


def test_neighbors_default_uses_property_filter() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params["query"]
        return httpx.Response(200, json=_SPARQL_RESPONSE)

    with _kb(handler) as kb:
        kb.neighbors("Q42")
    # the no-rels branch filters predicates to direct properties rather than
    # binding a VALUES clause.
    assert "VALUES ?p" not in captured["query"]
    assert "prop/direct/" in captured["query"]


def _sparql_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_SPARQL_RESPONSE)


def test_neighbors_rejects_malformed_ref() -> None:
    with (
        _kb(_sparql_handler) as kb,
        pytest.raises(WikidataError, match="entity identifier"),
    ):
        kb.neighbors("Q42 } INJECT")


def test_neighbors_rejects_malformed_rel() -> None:
    with (
        _kb(_sparql_handler) as kb,
        pytest.raises(WikidataError, match="property identifier"),
    ):
        kb.neighbors("Q42", rels=["P31; DROP"])


def test_default_client_carries_user_agent() -> None:
    with WikidataKB() as kb:
        assert kb._client.headers["User-Agent"] == DEFAULT_USER_AGENT


def test_search_ignores_types_argument() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_SEARCH_RESPONSE)

    with _kb(handler) as kb:
        with_types = kb.search("Adams", types=["Q5"])
        without = kb.search("Adams")
    # the action API carries no type parameter; results are identical.
    assert "type" not in seen
    assert with_types == without


def test_search_lang_override_is_used_and_keys_cache() -> None:
    langs: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        langs.append(request.url.params["language"])
        return httpx.Response(200, json=_SEARCH_RESPONSE)

    with _kb(handler) as kb:
        kb.search("Adams", lang="fr")
        kb.search("Adams", lang="fr")  # cached: no second request
        kb.search("Adams", lang="de")  # distinct cache key: new request
    assert langs == ["fr", "de"]


def test_search_respects_custom_limit() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_SEARCH_RESPONSE)

    transport = httpx.MockTransport(handler)
    with WikidataKB(client=httpx.Client(transport=transport), limit=3) as kb:
        kb.search("Adams")
    assert seen["limit"] == "3"


def test_search_score_never_negative() -> None:
    # eleven hits against the default limit of ten would drive the naive
    # 1 - rank/limit score negative for rank >= 10; it is clamped at zero.
    many: JsonValue = {"search": [{"id": f"Q{i}"} for i in range(11)]}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=many)

    with _kb(handler) as kb:
        candidates = kb.search("Adams")
    assert all(candidate.score >= 0.0 for candidate in candidates)
    assert candidates[-1].score == 0.0


def test_search_label_falls_back_to_match_and_display() -> None:
    assert _search_label({"id": "Q1", "label": "labelled"}) == "labelled"
    assert (
        _search_label({"id": "Q1", "display": {"label": {"value": "displayed"}}})
        == "displayed"
    )
    assert _search_label({"id": "Q1", "match": {"text": "matched"}}) == "matched"
    # with nothing readable, the bare id stands in rather than an empty string.
    assert _search_label({"id": "Q1"}) == "Q1"


def test_resolve_entity_with_missing_terms() -> None:
    sparse: JsonValue = {"entities": {"Q7": {}}}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sparse)

    with _kb(handler) as kb:
        entity = kb.resolve("Q7")
    assert entity.ref == "Q7"
    assert entity.label == ""
    assert entity.description is None
    assert entity.aliases == ()
    assert entity.types == ()
    assert entity.same_as == ()


def _wikidata_routes(path: str, _params: dict[str, str]) -> tuple[int, JsonValue]:
    """Serve the three Wikidata endpoints the connector uses, from fixtures."""
    if path.endswith("/Q42.json"):
        return 200, _ENTITY_DATA
    if path.endswith("/api"):
        return 200, _SEARCH_RESPONSE
    return 200, _SPARQL_RESPONSE


@pytest.mark.integration
def test_wikidata_against_loopback_server(
    route_server: Callable[[RouteHandler], AbstractContextManager[str]],
) -> None:
    # exercise resolve/search/neighbors end-to-end over the real httpx transport
    # against a loopback server, so the connector runs without reaching the
    # public Wikidata endpoints.
    with route_server(_wikidata_routes) as base, httpx.Client() as client:
        kb = WikidataKB(
            endpoint=f"{base}/sparql",
            api_endpoint=f"{base}/api",
            entity_endpoint=base,
            client=client,
        )
        entity = kb.resolve("Q42")
        candidates = kb.search("Douglas")
        edges = kb.neighbors("Q42")
    assert entity.ref == "Q42"
    assert entity.label == "Douglas Adams"
    assert candidates[0].ref == "Q42"
    assert edges
    assert isinstance(edges[0], Edge)
