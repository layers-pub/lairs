"""Unit tests for lairs.store.pool."""

from __future__ import annotations

import pytest

from lairs.records.blobref import BlobRef
from lairs.store import pool


def test_exports() -> None:
    assert set(pool.__all__) == {"ModelPool"}


def test_add_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        pool.ModelPool().add("at://x", BlobRef(cid="a"))


def test_resolve_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        pool.ModelPool().resolve("at://x")


def test_backrefs_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        pool.ModelPool().backrefs("at://x")
