"""Unit tests for lairs.records.views."""

from __future__ import annotations

import pytest

from lairs.records import views
from lairs.records.blobref import BlobRef


def test_exports() -> None:
    assert set(views.__all__) == {"anchor_kind", "explode_layer"}


def test_anchor_kind_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        views.anchor_kind(BlobRef(cid="a"))


def test_explode_layer_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        views.explode_layer(BlobRef(cid="a"))
