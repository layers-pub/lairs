"""Unit and integration tests for lairs.discovery.ingest."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto.firehose import FirehoseEvent
from lairs.atproto.pds import PdsClient, RecordEnvelope, RepoDescription
from lairs.discovery import ingest
from lairs.discovery.index import DiscoveryIndex
from lairs.discovery.ingest import build_index, update_index

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from conftest import PdsServer

    from lairs._types import JsonValue

_CORPUS_NSID = "pub.layers.corpus.corpus"
_URI_A = "at://did:plc:x/pub.layers.corpus.corpus/a"
_CORPUS_VALUE: JsonValue = {
    "$type": _CORPUS_NSID,
    "name": "indexed corpus",
    "createdAt": "2026-06-18T00:00:00Z",
    "domain": "biomedical",
}


class _FakeRepo:
    """A fake describer and corpus lister for crawl unit tests."""

    def __init__(
        self,
        collections: tuple[str, ...],
        envelopes: list[RecordEnvelope],
    ) -> None:
        self._collections = collections
        self._envelopes = envelopes

    def describe_repo(self, repo: str) -> RepoDescription:
        return RepoDescription(
            did=repo,
            handle="alice.test",
            collections=self._collections,
        )

    def list_records(self, repo: str, collection: str) -> Iterator[RecordEnvelope]:
        _ = (repo, collection)
        yield from self._envelopes


@pytest.mark.integration
def test_build_index_indexes_corpora(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    envelope = RecordEnvelope(uri=_URI_A, cid="bafy", value=_CORPUS_VALUE)
    fake = _FakeRepo((_CORPUS_NSID,), [envelope])
    report = build_index(
        index,
        ["did:plc:x"],
        describe=fake,
        list_corpora=fake,
        endpoint="https://pds.example",
    )
    assert report.repos_with_corpora == 1
    assert report.cards_built == 1
    assert index.get_card(_URI_A) is not None


@pytest.mark.integration
def test_build_index_logs_repo_without_corpus(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    fake = _FakeRepo(("app.bsky.feed.post",), [])
    report = build_index(
        index,
        ["did:plc:x"],
        describe=fake,
        list_corpora=fake,
        endpoint="https://pds.example",
    )
    assert report.repos_with_corpora == 0
    assert any("no pub.layers.corpus.corpus" in reason for reason in report.skipped)


@pytest.mark.integration
def test_build_index_logs_max_repos_bound(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    fake = _FakeRepo((_CORPUS_NSID,), [])
    report = build_index(
        index,
        ["did:plc:a", "did:plc:b"],
        describe=fake,
        list_corpora=fake,
        endpoint="https://pds.example",
        max_repos=1,
    )
    assert report.repos_seen == 1
    assert any("bound reached" in reason for reason in report.skipped)


@pytest.mark.integration
def test_update_index_from_firehose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    events = [
        FirehoseEvent(
            seq=5,
            repo="did:plc:x",
            collection=_CORPUS_NSID,
            rkey="a",
            action="create",
            record=_CORPUS_VALUE,
        ),
    ]

    def fake_subscribe(
        relay: str,
        *,
        nsids: Sequence[str] | None = None,
        cursor: int | None = None,
    ) -> Iterator[FirehoseEvent]:
        _ = (relay, nsids, cursor)
        yield from events

    monkeypatch.setattr(ingest, "subscribe_repos", fake_subscribe)
    report = update_index(index, "wss://relay.example", limit=1)
    assert report.cards_built == 1
    assert index.get_card(_URI_A) is not None
    cursor = index.get_cursor("wss://relay.example")
    assert cursor is not None
    assert cursor.seq == 5


def _seed_corpus(server: PdsServer, name: str) -> None:
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {server.access_jwt}"},
        json={
            "repo": server.did,
            "collection": _CORPUS_NSID,
            "record": {
                "$type": _CORPUS_NSID,
                "name": name,
                "createdAt": "2026-06-18T00:00:00Z",
            },
        },
        timeout=30.0,
    )
    response.raise_for_status()


@pytest.mark.integration
def test_build_index_live(pds_server: PdsServer, tmp_path: Path) -> None:
    _seed_corpus(pds_server, "crawled corpus")
    index = DiscoveryIndex.init(tmp_path / "idx")
    with PdsClient(pds_server.endpoint) as client:
        report = build_index(
            index,
            [pds_server.did],
            describe=client,
            list_corpora=client,
            endpoint=pds_server.endpoint,
        )
    assert report.repos_with_corpora == 1
    assert any(card.summary.name == "crawled corpus" for card in index.cards())


@pytest.mark.integration
def test_update_index_live(pds_server: PdsServer, tmp_path: Path) -> None:
    ws_endpoint = "ws://" + pds_server.endpoint.removeprefix("http://")
    index = DiscoveryIndex.init(tmp_path / "idx")
    failure: list[str] = []

    def consume() -> None:
        # no limit: tail and index every corpus commit, which writes each card to
        # the working tree as it arrives. the daemon thread is left tailing; the
        # test stops by polling for its specific card, which is robust to
        # firehose sequencer lag delivering an earlier corpus commit first.
        try:
            update_index(index, ws_endpoint)
        except Exception as exc:  # noqa: BLE001  (surface thread errors to the test)
            failure.append(repr(exc))

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    time.sleep(3.0)  # allow the websocket to connect and begin tailing
    _seed_corpus(pds_server, "firehose corpus")
    deadline = time.monotonic() + 20.0
    found = False
    while time.monotonic() < deadline:
        if any(card.summary.name == "firehose corpus" for card in index.cards()):
            found = True
            break
        time.sleep(0.5)
    assert not failure, failure
    assert found
