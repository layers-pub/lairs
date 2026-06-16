"""Unit tests for lairs.author.builders."""

from __future__ import annotations

import pytest

from lairs.author import builders
from lairs.records.blobref import BlobRef


def test_exports() -> None:
    assert set(builders.__all__) == {
        "bbox",
        "span",
        "spatio_temporal",
        "temporal",
        "token_ref",
    }


def test_span_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        builders.span(0, 4)


def test_token_ref_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        builders.token_ref("tok", 3)


def test_temporal_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        builders.temporal(0, 1000)


def test_bbox_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        builders.bbox(0.0, 0.0, 1.0, 1.0)


def test_spatio_temporal_is_a_stub() -> None:
    # the placeholder model is unused; the stub raises before touching it.
    placeholder = BlobRef(cid="placeholder")
    with pytest.raises(NotImplementedError):
        builders.spatio_temporal(placeholder, [placeholder], "linear")
