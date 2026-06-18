"""Unit and integration tests for lairs.atproto.appview."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto import appview
from lairs.atproto.appview import AppviewClient
from lairs.atproto.pds import RecordEnvelope

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from conftest import RouteHandler

    from lairs._types import JsonValue

_ENDPOINT = "https://appview.example"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> AppviewClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return AppviewClient(_ENDPOINT, client)


def test_exports() -> None:
    assert set(appview.__all__) == {"AppviewClient"}


def test_appview_client_constructs() -> None:
    client = AppviewClient("https://appview.example/")
    assert client.endpoint == "https://appview.example"


def test_query_prefixes_layers_nsid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.corpus.listCorpora"
        return httpx.Response(200, json={"records": []})

    with _client(handler) as client:
        body = client.query("corpus.listCorpora", {})
    assert body == {"records": []}


def test_query_accepts_full_nsid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.corpus.getCorpus"
        return httpx.Response(200, json={"uri": "at://x", "cid": "c", "value": {}})

    with _client(handler) as client:
        body = client.query("pub.layers.corpus.getCorpus", {"uri": "at://x"})
    assert body["uri"] == "at://x"


def test_get_returns_envelope() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"uri": "at://x", "cid": "bafy", "value": {"name": "ud"}},
        )

    with _client(handler) as client:
        envelope = client.get("corpus.getCorpus", {"uri": "at://x"})
    assert isinstance(envelope, RecordEnvelope)
    assert envelope.uri == "at://x"
    assert envelope.value == {"name": "ud"}


def test_list_paginates() -> None:
    pages = {
        None: {
            "records": [{"uri": "at://1", "cid": "c1", "value": {}}],
            "cursor": "p2",
        },
        "p2": {
            "records": [{"uri": "at://2", "cid": "c2", "value": {}}],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor])

    with _client(handler) as client:
        envelopes = list(client.list("corpus.listCorpora", {}))
    assert [e.uri for e in envelopes] == ["at://1", "at://2"]


def test_query_raises_on_error_status() -> None:
    with (
        _client(lambda _r: httpx.Response(503)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.query("corpus.listCorpora", {})


def _appview_routes(path: str, params: dict[str, str]) -> tuple[int, JsonValue]:
    """Serve a minimal Layers appview: one get method and one paged list."""
    if path == "/xrpc/pub.layers.corpus.getCorpus":
        return 200, {
            "uri": "at://did:plc:demo/pub.layers.corpus.corpus/abc",
            "cid": "bafycorpus",
            "value": {"name": "demo corpus"},
        }
    if path == "/xrpc/pub.layers.corpus.listCorpora":
        if params.get("cursor") is None:
            return 200, {
                "records": [{"uri": "at://1", "cid": "c1", "value": {}}],
                "cursor": "page2",
            }
        if params.get("cursor") == "page2":
            return 200, {"records": [{"uri": "at://2", "cid": "c2", "value": {}}]}
    return 404, {"error": "MethodNotImplemented"}


@pytest.mark.integration
def test_appview_queries_against_live_server(
    route_server: Callable[[RouteHandler], AbstractContextManager[str]],
) -> None:
    # drive the real httpx transport against a loopback appview: nsid prefixing,
    # get-envelope decoding, cursor pagination, and error propagation.
    with (
        route_server(_appview_routes) as base_url,
        AppviewClient(base_url) as client,
    ):
        envelope = client.get("corpus.getCorpus", {"uri": "at://x"})
        assert envelope.value == {"name": "demo corpus"}
        assert envelope.uri == "at://did:plc:demo/pub.layers.corpus.corpus/abc"
        listed = list(client.list("corpus.listCorpora", {}))
        assert [env.uri for env in listed] == ["at://1", "at://2"]
        with pytest.raises(httpx.HTTPStatusError):
            client.query("corpus.unknownMethod", {})
