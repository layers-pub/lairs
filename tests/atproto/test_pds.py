"""Unit and integration tests for lairs.atproto.pds."""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx
import httpx
import pytest

from lairs.atproto import pds
from lairs.atproto.pds import (
    PdsClient,
    RecordEnvelope,
    decode,
    decode_all,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_ENDPOINT = "https://pds.example"
_REPO = "did:plc:abc"
_COLLECTION = "pub.layers.expression.expression"


class _Toy(dx.Model):
    """A toy target model for decode tests."""

    text: str = dx.field(description="text")


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> PdsClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return PdsClient(_ENDPOINT, client)


def test_exports() -> None:
    assert set(pds.__all__) == {
        "PdsClient",
        "QueryParams",
        "RecordDecodeFailure",
        "RecordEnvelope",
        "decode",
        "decode_all",
        "get_record",
        "list_records",
    }


def test_get_record_returns_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.repo.getRecord"
        assert request.url.params["repo"] == _REPO
        return httpx.Response(
            200,
            json={"uri": "at://x", "cid": "bafy", "value": {"text": "hi"}},
        )

    with _client(handler) as client:
        envelope = client.get_record(_REPO, _COLLECTION, "rkey")
    assert isinstance(envelope, RecordEnvelope)
    assert envelope.uri == "at://x"
    assert envelope.cid == "bafy"
    assert envelope.value == {"text": "hi"}


def test_decode_helper_validates_value() -> None:
    envelope = RecordEnvelope(uri="at://x", cid="bafy", value={"text": "hi"})
    decoded = decode(envelope, _Toy)
    assert isinstance(decoded, _Toy)
    assert decoded.text == "hi"


def test_decode_helper_raises_on_invalid() -> None:
    envelope = RecordEnvelope(uri="at://x", cid="bafy", value={"nope": 1})
    with pytest.raises(dx.ValidationError):
        decode(envelope, _Toy)


def test_decode_all_collects_failures() -> None:
    envelopes = [
        RecordEnvelope(uri="at://1", cid="c1", value={"text": "ok"}),
        RecordEnvelope(uri="at://2", cid="c2", value={"nope": 1}),
        RecordEnvelope(uri="at://3", cid="c3", value={"text": "also"}),
    ]
    records, failures = decode_all(envelopes, _Toy)
    assert len(records) == 2
    assert all(isinstance(record, _Toy) for record in records)
    assert len(failures) == 1
    assert failures[0].uri == "at://2"
    assert failures[0].cid == "c2"
    assert failures[0].error


def test_list_records_paginates_lazily() -> None:
    pages = {
        None: {
            "records": [
                {"uri": "at://1", "cid": "c1", "value": {"text": "a"}},
                {"uri": "at://2", "cid": "c2", "value": {"text": "b"}},
            ],
            "cursor": "page2",
        },
        "page2": {
            "records": [
                {"uri": "at://3", "cid": "c3", "value": {"text": "c"}},
            ],
        },
    }
    seen_cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        seen_cursors.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    with _client(handler) as client:
        envelopes = list(client.list_records(_REPO, _COLLECTION))
    assert [e.uri for e in envelopes] == ["at://1", "at://2", "at://3"]
    assert seen_cursors == [None, "page2"]


def test_list_records_stops_on_empty_cursor() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "records": [{"uri": "at://1", "cid": "c1", "value": {}}],
                "cursor": "",
            },
        )

    with _client(handler) as client:
        envelopes = list(client.list_records(_REPO, _COLLECTION))
    assert len(envelopes) == 1


def test_list_records_is_lazy_iterator() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "records": [{"uri": "at://1", "cid": "c1", "value": {}}],
                    "cursor": "next",
                },
            )
        return httpx.Response(
            200,
            json={"records": [{"uri": "at://2", "cid": "c2", "value": {}}]},
        )

    with _client(handler) as client:
        iterator = client.list_records(_REPO, _COLLECTION)
        first = next(iterator)
        # only the first page should have been fetched so far.
        assert calls["n"] == 1
        assert first.uri == "at://1"
        rest = list(iterator)
    assert calls["n"] == 2
    assert [e.uri for e in rest] == ["at://2"]


def test_get_record_raises_on_error_status() -> None:
    with (
        _client(lambda _r: httpx.Response(500)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.get_record(_REPO, _COLLECTION, "rkey")


def test_get_repo_car_is_deferred() -> None:
    with (
        _client(lambda _r: httpx.Response(200)) as client,
        pytest.raises(NotImplementedError),
    ):
        client.get_repo_car(_REPO)


def test_module_list_records_drains_pages() -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(
            200,
            json={"records": [{"uri": "at://1", "cid": "c1", "value": {}}]},
        ),
    )
    client = httpx.Client(transport=transport)
    with PdsClient(_ENDPOINT, client) as pds_client:
        envelopes = list(pds_client.list_records(_REPO, _COLLECTION))
    assert len(envelopes) == 1


@pytest.mark.integration
def test_get_record_live() -> None:
    # exercises a real PDS getRecord when opted in; skips otherwise.
    try:
        pds.get_record(
            _ENDPOINT,
            _REPO,
            "pub.layers.corpus.corpus",
            "rkey",
        )
    except httpx.HTTPError:
        pytest.skip("network unavailable for live pds getRecord")
