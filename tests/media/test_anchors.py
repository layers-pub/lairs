"""Unit tests for lairs.media.anchors."""

from __future__ import annotations

import pytest

from lairs.media import anchors
from lairs.records.blobref import BlobRef


def test_exports() -> None:
    assert set(anchors.__all__) == {"AnchorTarget", "resolve_anchor"}


def test_resolve_anchor_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        anchors.resolve_anchor(BlobRef(cid="a"), BlobRef(cid="b"))
