"""Unit and integration tests for lairs.integrations.kb.reconciliation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.integrations.kb import Candidate, Edge, Entity
from lairs.integrations.kb.reconciliation import (
    ReconciliationError,
    ReconciliationKB,
)
from lairs.integrations.ports import KnowledgeBase

if TYPE_CHECKING:
    from collections.abc import Callable

    from lairs._types import JsonValue

_ENDPOINT = "https://recon.example/api"

_QUERIES_RESPONSE = {
    "q0": {
        "result": [
            {
                "id": "Q42",
                "name": "Douglas Adams",
                "score": 88.0,
                "type": [{"id": "Q5", "name": "human"}],
            },
            {"id": "Q5", "name": "human", "score": 12.5},
        ],
    },
}

_MANIFEST = {
    "name": "Example reconciliation",
    "extend": {
        "propose_properties": {
            "properties": [{"id": "P31"}, {"id": "P569"}],
        },
    },
    "suggest": {
        "entity": {
            "service_url": "https://recon.example",
            "service_path": "/suggest/entity",
        },
    },
}

_EXTEND_RESPONSE = {
    "rows": {
        "Q42": {
            "P31": [{"id": "Q5", "name": "human"}],
            "P569": [{"str": "1952-03-11"}],
        },
    },
}

_SUGGEST_RESPONSE = {"result": [{"id": "Q42", "name": "Douglas Adams"}]}


def _kb(handler: Callable[[httpx.Request], httpx.Response]) -> ReconciliationKB:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return ReconciliationKB(_ENDPOINT, client)


def test_name() -> None:
    assert ReconciliationKB.name == "reconciliation"


def test_conforms_to_port() -> None:
    assert isinstance(ReconciliationKB(_ENDPOINT), KnowledgeBase)


def test_endpoint_trailing_slash_stripped() -> None:
    assert ReconciliationKB("https://recon.example/api/").endpoint == _ENDPOINT


def test_search_parses_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json=_QUERIES_RESPONSE)

    with _kb(handler) as kb:
        candidates = kb.search("Adams")
    assert all(isinstance(candidate, Candidate) for candidate in candidates)
    assert candidates[0] == Candidate(ref="Q42", label="Douglas Adams", score=88.0)
    assert candidates[1].ref == "Q5"


def test_search_passes_lang_and_types() -> None:
    seen: dict[str, JsonValue] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body["queries"]["q0"])
        return httpx.Response(200, json={"q0": {"result": []}})

    with _kb(handler) as kb:
        kb.search("Adams", lang="en", types=["Q5"])
    assert seen["lang"] == "en"
    assert seen["type"] == ["Q5"]


def test_search_is_cached() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_QUERIES_RESPONSE)

    with _kb(handler) as kb:
        first = kb.search("Adams")
        second = kb.search("Adams")
    assert calls["n"] == 1
    assert first == second


def test_resolve_extends_entity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/suggest/entity"):
            return httpx.Response(200, json=_SUGGEST_RESPONSE)
        if request.method == "GET":
            return httpx.Response(200, json=_MANIFEST)
        return httpx.Response(200, json=_EXTEND_RESPONSE)

    with _kb(handler) as kb:
        entity = kb.resolve("Q42")
    assert isinstance(entity, Entity)
    assert entity.ref == "Q42"
    assert "1952-03-11" in entity.same_as
    assert "Q5" in entity.same_as
    assert entity.label == "Douglas Adams"


def test_resolve_is_cached() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.method == "GET" and request.url.path.endswith("/suggest/entity"):
            return httpx.Response(200, json=_SUGGEST_RESPONSE)
        if request.method == "GET":
            return httpx.Response(200, json=_MANIFEST)
        return httpx.Response(200, json=_EXTEND_RESPONSE)

    with _kb(handler) as kb:
        kb.resolve("Q42")
        before = calls["n"]
        kb.resolve("Q42")
    assert calls["n"] == before


def test_resolve_without_extend_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "no extend service"})

    with _kb(handler) as kb, pytest.raises(ReconciliationError, match="extension"):
        kb.resolve("Q42")


def test_neighbors_builds_edges() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_MANIFEST)
        return httpx.Response(200, json=_EXTEND_RESPONSE)

    with _kb(handler) as kb:
        edges = kb.neighbors("Q42")
    assert all(isinstance(edge, Edge) for edge in edges)
    # only the cell carrying an entity id becomes an edge; the literal does not.
    assert edges == [Edge(source="Q42", relation="P31", target="Q5")]


def test_neighbors_honours_rel_filter() -> None:
    requested: dict[str, JsonValue] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_MANIFEST)
        requested.update(json.loads(request.content)["extend"])
        return httpx.Response(200, json=_EXTEND_RESPONSE)

    with _kb(handler) as kb:
        kb.neighbors("Q42", rels=["P31"])
    assert requested["properties"] == [{"id": "P31"}]


def test_neighbors_without_extend_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "no extend"})

    with _kb(handler) as kb, pytest.raises(ReconciliationError):
        kb.neighbors("Q42")


@pytest.mark.integration
def test_resolve_live() -> None:
    pytest.skip("requires network access to a reconciliation endpoint")
