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


@pytest.mark.integration
def test_query_live() -> None:
    # exercises a real appview query when opted in; skips otherwise.
    client = AppviewClient(_ENDPOINT)
    try:
        client.query("corpus.listCorpora", {})
    except httpx.HTTPError:
        pytest.skip("network unavailable for live appview query")
    finally:
        client.close()
