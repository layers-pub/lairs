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
from lairs.records._generated.expression import Expression

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import PdsServer

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
    assert len(failures) == 1
    assert all(isinstance(record, _Toy) for record in records)
    assert failures[0].uri == "at://2"
    assert failures[0].cid == "c2"
    assert failures[0].error


def test_decode_coerces_datetime_fields() -> None:
    # regression: dict-path model_validate raises a bare AssertionError on
    # datetime strings; the json path coerces them, so records carrying a
    # createdAt (every pub.layers record does) decode cleanly.
    envelope = RecordEnvelope(
        uri="at://x",
        cid="bafy",
        value={
            "id": "00000000-0000-0000-0000-000000000000",
            "text": "hi",
            "kind": "sentence",
            "createdAt": "2026-06-16T00:00:00Z",
        },
    )
    assert decode(envelope, Expression).text == "hi"
    records, failures = decode_all([envelope], Expression)
    assert len(records) == 1
    assert not failures


def test_decode_strips_type_discriminator() -> None:
    # real PDS records carry a $type the generated models do not declare.
    envelope = RecordEnvelope(
        uri="at://x",
        cid="bafy",
        value={"$type": "pub.layers.x", "text": "hi"},
    )
    assert decode(envelope, _Toy).text == "hi"


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


@pytest.mark.integration
def test_pds_round_trip_live(pds_server: PdsServer) -> None:
    """Seed a record on a real PDS and read it back through the client."""
    value = {
        "$type": "pub.layers.expression.expression",
        "id": "11111111-1111-1111-1111-111111111111",
        "text": "the cat sat",
        "kind": "sentence",
        "createdAt": "2026-06-16T00:00:00Z",
    }
    headers = {"Authorization": f"Bearer {pds_server.access_jwt}"}
    with httpx.Client(headers=headers) as authed:
        created = authed.post(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": pds_server.did,
                "collection": "pub.layers.expression.expression",
                "record": value,
            },
            timeout=30.0,
        )
        created.raise_for_status()
        uri = str(created.json()["uri"])
    rkey = uri.rsplit("/", 1)[-1]
    client = PdsClient(pds_server.endpoint)
    envelope = client.get_record(
        pds_server.did, "pub.layers.expression.expression", rkey
    )
    assert decode(envelope, Expression).text == "the cat sat"
    listed = list(
        client.list_records(pds_server.did, "pub.layers.expression.expression"),
    )
    assert any(env.uri == uri for env in listed)
