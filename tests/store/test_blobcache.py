"""Unit and integration tests for lairs.store.blobcache."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lairs.store import blobcache
from lairs.store.blobcache import BlobCache

if TYPE_CHECKING:
    from pathlib import Path

_CID = "bafkreigh2akiscaildc"


def test_exports() -> None:
    assert set(blobcache.__all__) == {"BlobCache"}


def test_get_missing_returns_none(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    assert cache.get(_CID) is None
    assert cache.exists(_CID) is False


def test_put_then_get_round_trip(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    path = cache.put(_CID, b"audio-bytes")
    assert path.is_file()
    assert cache.exists(_CID) is True
    assert cache.get(_CID) == b"audio-bytes"


def test_path_for_is_content_addressed(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    expected = tmp_path / "blobs" / _CID
    assert cache.path_for(_CID) == expected


def test_put_is_idempotent_for_same_content(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    cache.put(_CID, b"data")
    cache.put(_CID, b"data")
    assert cache.get(_CID) == b"data"


def test_different_cids_are_distinct(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    cache.put("cid-a", b"a")
    cache.put("cid-b", b"b")
    assert cache.get("cid-a") == b"a"
    assert cache.get("cid-b") == b"b"


@pytest.mark.integration
def test_cache_shared_across_instances(tmp_path: Path) -> None:
    BlobCache(tmp_path).put(_CID, b"shared")
    assert BlobCache(tmp_path).get(_CID) == b"shared"
