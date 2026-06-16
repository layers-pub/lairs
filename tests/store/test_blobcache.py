"""Unit tests for lairs.store.blobcache."""

from __future__ import annotations

from pathlib import Path

import pytest

from lairs.store import blobcache


def test_exports() -> None:
    assert set(blobcache.__all__) == {"BlobCache"}


def test_get_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        blobcache.BlobCache(Path("cache")).get("bafy")


def test_put_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        blobcache.BlobCache(Path("cache")).put("bafy", b"x")
