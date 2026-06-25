"""Unit and integration tests for lairs.store.blobcache."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from multiformats import CID, multihash

from lairs.store import blobcache
from lairs.store.blobcache import BlobCache, BlobCacheError

if TYPE_CHECKING:
    from pathlib import Path

# an opaque, non-CID cache key (a truncated string that does not decode).
_CID = "bafkreigh2akiscaildc"


def _real_cid(data: bytes) -> str:
    """Return the raw-codec CIDv1 that addresses ``data``."""
    return str(CID("base32", 1, "raw", multihash.digest(data, "sha2-256")))


def test_exports() -> None:
    assert set(blobcache.__all__) == {"BlobCache", "BlobCacheError"}


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


def test_put_real_cid_round_trip(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    data = b"real content addressed bytes"
    cid = _real_cid(data)
    cache.put(cid, data)
    assert cache.get(cid) == data


def test_put_wrong_cid_raises(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    # a CID that addresses one payload cannot be used to store a different one.
    cid = _real_cid(b"the-true-content")
    with pytest.raises(BlobCacheError, match="do not match"):
        cache.put(cid, b"tampered-content")
    # nothing was written, so the bad CID never poisons the cache.
    assert cache.get(cid) is None


def test_put_wrong_cid_can_skip_verification(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    cid = _real_cid(b"the-true-content")
    # verify=False trusts the caller; the bytes are stored as given.
    cache.put(cid, b"trusted-bytes", verify=False)
    assert cache.get(cid) == b"trusted-bytes"


def test_put_rejects_path_separator(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    with pytest.raises(BlobCacheError, match="safe path component"):
        cache.put("nested/escape", b"x")


def test_put_rejects_parent_reference(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    with pytest.raises(BlobCacheError, match="safe path component"):
        cache.put("..", b"x")


def test_path_for_rejects_path_separator(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    with pytest.raises(BlobCacheError, match="safe path component"):
        cache.path_for("a/b")


def test_put_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    cache = BlobCache(tmp_path)
    cache.put(_CID, b"data")
    blobs = tmp_path / "blobs"
    # the atomic rename leaves only the final blob, no scratch *.tmp file.
    names = sorted(child.name for child in blobs.iterdir())
    assert names == [_CID]


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
