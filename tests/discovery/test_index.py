"""Unit and integration tests for lairs.discovery.index."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lairs.discovery.cards import (
    CardFreshness,
    CardProvenance,
    DatasetCard,
    RepoCrawlState,
    SyncCursor,
)
from lairs.discovery.index import DiscoveryIndex, default_index_path
from lairs.discovery.models import DatasetSummary

_NOW = datetime(2026, 6, 18, tzinfo=UTC)


def _card(corpus_uri: str, name: str) -> DatasetCard:
    return DatasetCard(
        summary=DatasetSummary(uri=corpus_uri, did="did:plc:x", name=name),
        provenance=CardProvenance(
            source_did="did:plc:x",
            source_endpoint="https://pds.example",
            discovered_via="crawl",
        ),
        freshness=CardFreshness(first_seen_at=_NOW, last_updated_at=_NOW),
    )


_URI_A = "at://did:plc:x/pub.layers.corpus.corpus/a"
_URI_B = "at://did:plc:x/pub.layers.corpus.corpus/b"


def test_put_and_get_card_round_trip(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    card = _card(_URI_A, "demo")
    index.put_card(card)
    assert index.get_card(_URI_A) == card


def test_get_card_absent_returns_none(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    assert index.get_card(_URI_A) is None


def test_cards_lists_all(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(_card(_URI_A, "a"))
    index.put_card(_card(_URI_B, "b"))
    names = {card.summary.name for card in index.cards()}
    assert names == {"a", "b"}


def test_card_pool_keys_by_index_uri(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(_card(_URI_A, "a"))
    pool = index.card_pool()
    assert len(pool) == 1


@pytest.mark.integration
def test_remove_card_removes_from_index(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(_card(_URI_A, "a"))
    index.commit("seed")
    assert index.get_card(_URI_A) is not None
    assert index.remove_card(_URI_A) is True
    assert index.get_card(_URI_A) is None
    assert index.cards() == []


@pytest.mark.integration
def test_remove_card_absent_is_noop(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(_card(_URI_A, "a"))
    index.commit("seed")
    assert index.remove_card(_URI_B) is False
    assert index.get_card(_URI_A) is not None


@pytest.mark.integration
def test_diff_cards_reports_removed(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(_card(_URI_A, "a"))
    base = index.commit("first snapshot")
    assert index.remove_card(_URI_A) is True
    head = index.commit("drop a")
    diff = index.diff_cards(base, head)
    # a removed card is absent from the live index, so it falls back to the
    # card's own index URI (documented CardDiff behavior).
    assert len(diff.removed) == 1
    assert diff.removed[0].startswith("at://did:lairs:index/lairs.index.datasetCard/")
    assert diff.added == ()
    assert diff.changed == ()


def test_cursor_round_trip(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    assert index.get_cursor("wss://relay.example") is None
    cursor = SyncCursor(relay="wss://relay.example", seq=42, updated_at=_NOW)
    index.put_cursor(cursor)
    assert index.get_cursor("wss://relay.example") == cursor


def test_crawl_state_round_trip(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    state = RepoCrawlState(
        did="did:plc:x",
        endpoint="https://pds.example",
        has_layers_corpus=True,
        corpora_found=3,
        last_crawled_at=_NOW,
    )
    index.put_crawl_state(state)
    assert index.get_crawl_state("did:plc:x") == state


@pytest.mark.integration
def test_commit_and_diff_cards(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(_card(_URI_A, "a"))
    base = index.commit("first snapshot")
    index.put_card(_card(_URI_A, "a renamed"))
    index.put_card(_card(_URI_B, "b"))
    head = index.commit("second snapshot")
    diff = index.diff_cards(base, head)
    assert _URI_B in diff.added
    assert _URI_A in diff.changed
    assert diff.removed == ()


# ---- mute / unmute --------------------------------------------------------


def test_mute_removes_card_and_records_mute(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    card = _card(_URI_A, "Alpha")
    index.put_card(card)
    index.mute(card)
    assert index.get_card(_URI_A) is None
    assert index.is_muted(_URI_A) is True
    records = index.muted()
    assert len(records) == 1
    assert records[0].uri == _URI_A
    assert records[0].name == "Alpha"
    assert records[0].source_endpoint == "https://pds.example"


def test_unmute_clears_mute(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.mute(_card(_URI_A, "Alpha"))
    assert index.unmute(_URI_A) is True
    assert index.is_muted(_URI_A) is False
    assert index.muted() == []


def test_unmute_unknown_is_noop(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    assert index.unmute(_URI_A) is False


def test_is_muted_false_when_absent(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    assert index.is_muted(_URI_A) is False


@pytest.mark.integration
def test_mute_survives_commit_round_trip(tmp_path: Path) -> None:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.mute(_card(_URI_A, "Alpha"))
    index.commit("mute")
    reopened = DiscoveryIndex.open(tmp_path / "idx")
    assert reopened.is_muted(_URI_A) is True
    assert [record.uri for record in reopened.muted()] == [_URI_A]


# ---- default_index_path ---------------------------------------------------


def test_default_index_path_honors_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LAIRS_INDEX_DIR", str(tmp_path / "custom"))
    assert default_index_path() == tmp_path / "custom"


def test_default_index_path_uses_xdg_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("LAIRS_INDEX_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_index_path() == tmp_path / "state" / "lairs" / "index"


def test_default_index_path_falls_back_to_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("LAIRS_INDEX_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert (
        default_index_path()
        == tmp_path / "home" / ".local" / "state" / "lairs" / "index"
    )
