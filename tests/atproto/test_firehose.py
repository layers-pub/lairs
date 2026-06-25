"""Unit and integration tests for lairs.atproto.firehose."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import httpx
import libipld
import pytest
from websockets.exceptions import ConnectionClosed

from lairs.atproto import firehose
from lairs.atproto.firehose import (
    FirehoseEvent,
    RepoSubscriber,
    _commit_events,
    _keep_predicate,
    _op_event,
    _subscription_url,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from conftest import PdsServer

    from lairs.atproto._car import IpldValue

_COLLECTION = "pub.layers.expression.expression"


def _frame(header: IpldValue, body: IpldValue) -> bytes:
    """Concatenate a header and body into a single firehose frame."""
    return libipld.encode_dag_cbor(header) + libipld.encode_dag_cbor(body)


def test_exports() -> None:
    assert set(firehose.__all__) == {
        "FirehoseEvent",
        "RepoSubscriber",
        "subscribe_repos",
    }


def test_firehose_event_model_round_trips() -> None:
    event = FirehoseEvent(
        seq=7,
        repo="did:plc:abc",
        collection=_COLLECTION,
        rkey="rk",
        action="create",
        record={"text": "hi"},
    )
    dumped = event.model_dump()
    assert dumped["seq"] == 7
    assert dumped["action"] == "create"
    restored = FirehoseEvent.model_validate(dumped)
    assert restored.record == {"text": "hi"}


def test_repo_subscriber_is_runtime_checkable() -> None:
    class _Sub:
        def subscribe(
            self,
            *,
            nsids: Sequence[str] | None = None,
            cursor: int | None = None,
        ) -> Iterator[FirehoseEvent]:
            _ = (nsids, cursor)
            return iter(())

    assert isinstance(_Sub(), RepoSubscriber)


def test_subscription_url_appends_xrpc_path() -> None:
    url = _subscription_url("ws://localhost:3000", None)
    assert url == "ws://localhost:3000/xrpc/com.atproto.sync.subscribeRepos"


def test_subscription_url_preserves_path_and_adds_cursor() -> None:
    full = "wss://relay.example/xrpc/com.atproto.sync.subscribeRepos"
    assert _subscription_url(full, 42) == f"{full}?cursor=42"


def test_keep_predicate_default_keeps_layers() -> None:
    keep = _keep_predicate(None)
    assert keep("pub.layers.expression.expression")
    assert not keep("app.bsky.feed.post")


def test_keep_predicate_explicit_nsids() -> None:
    keep = _keep_predicate(["pub.layers.corpus.corpus"])
    assert keep("pub.layers.corpus.corpus")
    assert not keep("pub.layers.expression.expression")


def test_commit_events_yields_delete_for_layers_op() -> None:
    header: IpldValue = {"op": 1, "t": "#commit"}
    body: IpldValue = {
        "seq": 9,
        "repo": "did:plc:abc",
        "blocks": b"",
        "ops": [{"path": f"{_COLLECTION}/rk", "action": "delete", "cid": None}],
    }
    events = list(_commit_events(_frame(header, body), _keep_predicate(None)))
    assert len(events) == 1
    assert events[0].seq == 9
    assert events[0].action == "delete"
    assert events[0].collection == _COLLECTION
    assert events[0].rkey == "rk"
    assert events[0].record is None


def test_commit_events_filters_non_layers_ops() -> None:
    header: IpldValue = {"op": 1, "t": "#commit"}
    body: IpldValue = {
        "seq": 1,
        "repo": "did:plc:x",
        "blocks": b"",
        "ops": [{"path": "app.bsky.feed.post/rk", "action": "create", "cid": None}],
    }
    assert list(_commit_events(_frame(header, body), _keep_predicate(None))) == []


def test_commit_events_skips_non_commit_frames() -> None:
    header: IpldValue = {"op": 1, "t": "#identity"}
    body: IpldValue = {"seq": 1, "did": "did:plc:x"}
    assert list(_commit_events(_frame(header, body), _keep_predicate(None))) == []


def test_op_event_resolves_record_from_store() -> None:
    cid = b"\x01q\x12 " + bytes(32)
    record: IpldValue = {"$type": _COLLECTION, "text": "hi"}
    store: dict[bytes, IpldValue] = {cid: record}
    op: IpldValue = {"path": f"{_COLLECTION}/rk", "action": "create", "cid": cid}
    event = _op_event(op, 3, "did:plc:abc", store, _keep_predicate(None))
    assert event is not None
    assert event.action == "create"
    assert event.record == {"$type": _COLLECTION, "text": "hi"}


def test_op_event_delete_has_no_record() -> None:
    op: IpldValue = {"path": "pub.layers.x.y/rk", "action": "delete", "cid": None}
    store: dict[bytes, IpldValue] = {}
    event = _op_event(op, 1, "did:plc:abc", store, _keep_predicate(None))
    assert event is not None
    assert event.record is None


def test_op_event_filters_unkept_collection() -> None:
    op: IpldValue = {"path": "app.bsky.feed.post/rk", "action": "create", "cid": None}
    store: dict[bytes, IpldValue] = {}
    assert _op_event(op, 1, "did:plc:abc", store, _keep_predicate(None)) is None


class _FakeWebSocket:
    """A fake sync websocket that replays frames then closes."""

    def __init__(self, frames: list[bytes]) -> None:
        self._frames = list(frames)

    def recv(self) -> bytes:
        if self._frames:
            return self._frames.pop(0)
        raise ConnectionClosed(None, None)


def _commit_frame(seq: int) -> bytes:
    """Build a single create-commit frame for one Layers record."""
    header: IpldValue = {"op": 1, "t": "#commit"}
    body: IpldValue = {
        "seq": seq,
        "repo": "did:plc:abc",
        "blocks": b"",
        "ops": [{"path": f"{_COLLECTION}/rk{seq}", "action": "create", "cid": None}],
    }
    return _frame(header, body)


def test_subscribe_repos_ends_on_close_without_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the default single-connection primitive ends iteration cleanly when the
    # websocket closes, dialing exactly once.
    dialed: list[str] = []

    @contextmanager
    def fake_connect(url: str, **_kwargs: object) -> Iterator[_FakeWebSocket]:
        dialed.append(url)
        yield _FakeWebSocket([_commit_frame(1), _commit_frame(2)])

    monkeypatch.setattr(firehose, "connect", fake_connect)
    events = list(firehose.subscribe_repos("ws://relay.example"))
    assert [event.seq for event in events] == [1, 2]
    assert len(dialed) == 1


def test_subscribe_repos_reconnects_from_highest_seq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # with reconnect=True a dropped connection is re-dialed, resuming from the
    # highest seq already delivered so the freshness loop survives a blip.
    dialed: list[str] = []
    connections = iter(
        [
            [_commit_frame(5), _commit_frame(6)],
            [_commit_frame(7)],
        ],
    )

    @contextmanager
    def fake_connect(url: str, **_kwargs: object) -> Iterator[_FakeWebSocket]:
        dialed.append(url)
        try:
            frames = next(connections)
        except StopIteration:
            frames = []
        yield _FakeWebSocket(frames)

    monkeypatch.setattr(firehose, "connect", fake_connect)
    stream = firehose.subscribe_repos("ws://relay.example", reconnect=True)
    collected = [next(stream).seq for _ in range(3)]
    assert isinstance(stream, Generator)
    stream.close()
    assert collected == [5, 6, 7]
    # the first dial carries no cursor; the reconnect resumes from seq 6.
    assert dialed[0] == "ws://relay.example/xrpc/com.atproto.sync.subscribeRepos"
    assert dialed[1].endswith("?cursor=6")


@pytest.mark.integration
def test_subscribe_repos_live(pds_server: PdsServer) -> None:
    # tail the live firehose, create one record, and assert the consumer decodes
    # the matching commit event with its record value.
    ws_endpoint = "ws://" + pds_server.endpoint.removeprefix("http://")
    collection = "pub.layers.test.firehose"
    token = secrets.token_hex(4)
    captured: list[FirehoseEvent] = []
    failure: list[str] = []

    def consume() -> None:
        try:
            for event in firehose.subscribe_repos(ws_endpoint, nsids=[collection]):
                captured.append(event)
                break
        except Exception as exc:  # noqa: BLE001  (surface thread errors to the test)
            failure.append(repr(exc))

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    time.sleep(3.0)  # allow the websocket to connect and begin tailing
    created = httpx.post(
        f"{pds_server.endpoint}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {pds_server.access_jwt}"},
        json={
            "repo": pds_server.did,
            "collection": collection,
            "record": {
                "$type": collection,
                "id": "00000000-0000-0000-0000-000000000000",
                "text": f"firehose {token}",
                "kind": "sentence",
                "createdAt": "2026-06-18T00:00:00Z",
            },
        },
        timeout=30.0,
    )
    created.raise_for_status()
    thread.join(timeout=20.0)
    assert not failure, failure
    assert captured, "no firehose event was captured"
    event = captured[0]
    assert event.collection == collection
    assert event.action == "create"
    assert event.repo == pds_server.did
    record = event.record
    assert isinstance(record, dict)
    assert record["text"] == f"firehose {token}"
