"""Unit tests for lairs.media.resolve."""

from __future__ import annotations

import pytest

from lairs.media import resolve
from lairs.media.resolve import MediaHandle
from lairs.records.blobref import BlobRef


def test_exports() -> None:
    assert set(resolve.__all__) == {"MediaHandle", "resolve_media"}


def test_media_handle_construction() -> None:
    handle = MediaHandle(cid="bafy", mime_type="audio/wav", modality="audio")
    assert handle.cid == "bafy"
    assert handle.modality == "audio"
    assert handle.duration_ms is None


def test_resolve_media_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        resolve.resolve_media(BlobRef(cid="bafy"))
