"""Unit and integration tests for lairs.discovery.ingest."""

from __future__ import annotations

import secrets
import threading
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto.firehose import FirehoseEvent
from lairs.atproto.pds import (
    DEFAULT_PAGE_SIZE,
    PdsClient,
    RecordEnvelope,
    RepoDescription,
)
from lairs.discovery import ingest
from lairs.discovery.index import DiscoveryIndex
from lairs.discovery.ingest import build_index, discover, update_index

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
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


# ---- discover (streaming, index-free) -------------------------------------


class _BrokenDescriber:
    """A describer whose describe_repo always fails, to exercise skips."""

    def describe_repo(self, repo: str) -> RepoDescription:
        _ = repo
        msg = "boom"
        raise httpx.HTTPError(msg)

    def list_records(self, repo: str, collection: str) -> Iterator[RecordEnvelope]:
        _ = (repo, collection)
        yield from ()


def test_discover_yields_cards() -> None:
    envelope = RecordEnvelope(uri=_URI_A, cid="bafy", value=_CORPUS_VALUE)
    fake = _FakeRepo((_CORPUS_NSID,), [envelope])
    cards = list(
        discover(
            ["did:plc:x"],
            describe=fake,
            list_corpora=fake,
            endpoint="https://pds.example",
        ),
    )
    assert len(cards) == 1
    assert cards[0].summary.uri == _URI_A
    assert cards[0].summary.name == "indexed corpus"
    assert cards[0].provenance.discovered_via == "crawl"
    assert cards[0].provenance.source_endpoint == "https://pds.example"


def test_discover_skips_repo_without_corpus() -> None:
    fake = _FakeRepo(("app.bsky.feed.post",), [])
    cards = list(
        discover(
            ["did:plc:x"],
            describe=fake,
            list_corpora=fake,
            endpoint="https://pds.example",
        ),
    )
    assert cards == []


def test_discover_skips_describe_errors() -> None:
    broken = _BrokenDescriber()
    cards = list(
        discover(
            ["did:plc:x"],
            describe=broken,
            list_corpora=broken,
            endpoint="https://pds.example",
        ),
    )
    assert cards == []


def test_discover_skips_undecodable_corpus() -> None:
    # a malformed corpus record (missing required fields) is skipped, not raised,
    # so one bad record on a repo does not abort the crawl of the rest.
    bad = RecordEnvelope(
        uri="at://did:plc:x/pub.layers.corpus.corpus/bad",
        cid="bafybad",
        value={"$type": _CORPUS_NSID, "unexpected": "data"},
    )
    good = RecordEnvelope(
        uri="at://did:plc:x/pub.layers.corpus.corpus/good",
        cid="bafygood",
        value=_CORPUS_VALUE,
    )
    fake = _FakeRepo((_CORPUS_NSID,), [bad, good])
    cards = list(
        discover(
            ["did:plc:x"],
            describe=fake,
            list_corpora=fake,
            endpoint="https://pds.example",
        ),
    )
    assert [card.summary.uri for card in cards] == [
        "at://did:plc:x/pub.layers.corpus.corpus/good",
    ]


@pytest.mark.integration
def test_build_index_skips_muted(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    envelope = RecordEnvelope(uri=_URI_A, cid="bafy", value=_CORPUS_VALUE)
    fake = _FakeRepo((_CORPUS_NSID,), [envelope])
    [card] = discover(
        ["did:plc:x"],
        describe=fake,
        list_corpora=fake,
        endpoint="https://pds.example",
    )
    index.mute(card)
    report = build_index(
        index,
        ["did:plc:x"],
        describe=fake,
        list_corpora=fake,
        endpoint="https://pds.example",
    )
    assert index.get_card(_URI_A) is None
    assert report.cards_built == 0
    assert any("muted" in reason for reason in report.skipped)


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


def _fixed_subscribe(
    events: list[FirehoseEvent],
) -> Callable[..., Iterator[FirehoseEvent]]:
    def fake_subscribe(
        relay: str,
        *,
        nsids: Sequence[str] | None = None,
        cursor: int | None = None,
    ) -> Iterator[FirehoseEvent]:
        _ = (relay, nsids, cursor)
        yield from events

    return fake_subscribe


@pytest.mark.integration
def test_update_index_removes_card_on_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    create = FirehoseEvent(
        seq=5,
        repo="did:plc:x",
        collection=_CORPUS_NSID,
        rkey="a",
        action="create",
        record=_CORPUS_VALUE,
    )
    delete = FirehoseEvent(
        seq=6,
        repo="did:plc:x",
        collection=_CORPUS_NSID,
        rkey="a",
        action="delete",
        record=None,
    )
    monkeypatch.setattr(ingest, "subscribe_repos", _fixed_subscribe([create]))
    update_index(index, "wss://relay.example", limit=1)
    assert index.get_card(_URI_A) is not None

    monkeypatch.setattr(ingest, "subscribe_repos", _fixed_subscribe([delete]))
    report = update_index(index, "wss://relay.example", limit=1)
    assert report.cards_removed == 1
    assert report.cards_built == 0
    assert index.get_card(_URI_A) is None
    cursor = index.get_cursor("wss://relay.example")
    assert cursor is not None
    assert cursor.seq == 6


@pytest.mark.integration
def test_update_index_skips_delete_of_unindexed_corpus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    delete = FirehoseEvent(
        seq=7,
        repo="did:plc:x",
        collection=_CORPUS_NSID,
        rkey="a",
        action="delete",
        record=None,
    )
    monkeypatch.setattr(ingest, "subscribe_repos", _fixed_subscribe([delete]))
    report = update_index(index, "wss://relay.example", limit=1)
    assert report.cards_removed == 0
    assert any("delete of unindexed corpus" in reason for reason in report.skipped)


@pytest.mark.integration
def test_update_index_create_then_delete_in_one_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    create = FirehoseEvent(
        seq=8,
        repo="did:plc:x",
        collection=_CORPUS_NSID,
        rkey="a",
        action="create",
        record=_CORPUS_VALUE,
    )
    delete = FirehoseEvent(
        seq=9,
        repo="did:plc:x",
        collection=_CORPUS_NSID,
        rkey="a",
        action="delete",
        record=None,
    )
    monkeypatch.setattr(ingest, "subscribe_repos", _fixed_subscribe([create, delete]))
    report = update_index(index, "wss://relay.example", limit=2, commit_every=100)
    assert report.cards_built == 1
    assert report.cards_removed == 1
    assert index.get_card(_URI_A) is None


def _fresh_account(server: PdsServer) -> tuple[str, str]:
    """Create a new empty account on the PDS, returning (did, access_jwt).

    A fresh account isolates a crawl from corpora other live tests seed on the
    shared session account, so a count assertion is deterministic.
    """
    token = secrets.token_hex(6)
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.server.createAccount",
        json={
            "handle": f"ci{token}.test",
            "email": f"ci{token}@example.test",
            "password": secrets.token_hex(12),
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    return str(body["did"]), str(body["accessJwt"])


def _seed_corpus_on(server: PdsServer, did: str, jwt: str, name: str) -> str:
    """Create a corpus on a specific account and return its AT-URI."""
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {jwt}"},
        json={
            "repo": did,
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
    return str(response.json()["uri"])


def _seed_corpus(server: PdsServer, name: str) -> str:
    return _seed_corpus_on(server, server.did, server.access_jwt, name)


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
def test_discover_live(pds_server: PdsServer) -> None:
    # the real streaming crawl over a real PDS: two corpora on a fresh account
    # come back as cards with the right names, uris, and provenance.
    did, jwt = _fresh_account(pds_server)
    uri_a = _seed_corpus_on(pds_server, did, jwt, "live discover alpha")
    uri_b = _seed_corpus_on(pds_server, did, jwt, "live discover beta")
    with PdsClient(pds_server.endpoint) as client:
        cards = list(
            discover(
                [did],
                describe=client,
                list_corpora=client,
                endpoint=pds_server.endpoint,
            ),
        )
    by_uri = {card.summary.uri: card for card in cards}
    assert uri_a in by_uri
    assert uri_b in by_uri
    assert by_uri[uri_a].summary.name == "live discover alpha"
    assert by_uri[uri_a].provenance.source_did == did
    assert by_uri[uri_a].provenance.source_endpoint == pds_server.endpoint
    assert by_uri[uri_a].provenance.discovered_via == "crawl"


@pytest.mark.integration
def test_build_index_skips_muted_live(pds_server: PdsServer, tmp_path: Path) -> None:
    # muting a real corpus keeps a re-crawl of the real PDS from re-indexing it.
    did, jwt = _fresh_account(pds_server)
    uri = _seed_corpus_on(pds_server, did, jwt, "live mute target")
    index = DiscoveryIndex.init(tmp_path / "idx")
    with PdsClient(pds_server.endpoint) as client:
        discovered = [
            card
            for card in discover(
                [did],
                describe=client,
                list_corpora=client,
                endpoint=pds_server.endpoint,
            )
            if card.summary.uri == uri
        ]
        assert len(discovered) == 1
        index.mute(discovered[0])
        report = build_index(
            index,
            [did],
            describe=client,
            list_corpora=client,
            endpoint=pds_server.endpoint,
        )
    assert index.get_card(uri) is None
    assert index.is_muted(uri) is True
    assert any("muted" in reason for reason in report.skipped)


def _seed_corpora_bulk(server: PdsServer, did: str, jwt: str, count: int) -> None:
    """Create ``count`` corpora on ``did`` via batched applyWrites.

    Batching keeps seeding past the default page size fast (one request per
    chunk), so a pagination test does not pay for hundreds of round trips.
    """
    chunk = 50
    headers = {"Authorization": f"Bearer {jwt}"}
    with httpx.Client(headers=headers) as authed:
        created = 0
        while created < count:
            batch = min(chunk, count - created)
            writes = [
                {
                    "$type": "com.atproto.repo.applyWrites#create",
                    "collection": _CORPUS_NSID,
                    "value": {
                        "$type": _CORPUS_NSID,
                        "name": f"bulk corpus {created + offset}",
                        "createdAt": "2026-06-18T00:00:00Z",
                    },
                }
                for offset in range(batch)
            ]
            response = authed.post(
                f"{server.endpoint}/xrpc/com.atproto.repo.applyWrites",
                json={"repo": did, "writes": writes},
                timeout=60.0,
            )
            response.raise_for_status()
            created += batch


@pytest.mark.integration
def test_discover_drains_paginated_corpora_live(
    pds_server: PdsServer,
    tmp_path: Path,
) -> None:
    # an account with more corpora than one listRecords page must come back
    # whole: the crawl follows the real PDS cursor across every page at the
    # default page size, dropping and duplicating nothing at the boundaries.
    did, jwt = _fresh_account(pds_server)
    count = DEFAULT_PAGE_SIZE * 2 + 5
    _seed_corpora_bulk(pds_server, did, jwt, count)
    index = DiscoveryIndex.init(tmp_path / "idx")
    with PdsClient(pds_server.endpoint) as client:
        cards = list(
            discover(
                [did],
                describe=client,
                list_corpora=client,
                endpoint=pds_server.endpoint,
            ),
        )
        report = build_index(
            index,
            [did],
            describe=client,
            list_corpora=client,
            endpoint=pds_server.endpoint,
        )
    assert len(cards) == count
    assert len({card.summary.uri for card in cards}) == count
    assert report.cards_built == count
    assert len(index.cards()) == count


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
