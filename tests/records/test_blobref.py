"""Unit tests for lairs.records.blobref."""

from __future__ import annotations

import pytest

pytest.importorskip("didactic")

import didactic.api as dx

from lairs.records.blobref import BlobRef


def test_blobref_is_didactic_model() -> None:
    assert issubclass(BlobRef, dx.Model)


def test_blobref_minimal() -> None:
    ref = BlobRef(cid="bafy")
    assert ref.cid == "bafy"
    assert ref.mime_type is None
    assert ref.size is None


def test_blobref_full_and_roundtrip() -> None:
    ref = BlobRef(cid="bafy", mime_type="audio/wav", size=42)
    assert ref.mime_type == "audio/wav"
    assert ref.size == 42

    back = BlobRef.model_validate_json(ref.model_dump_json())
    assert back == ref


def test_blobref_is_immutable() -> None:
    ref = BlobRef(cid="bafy")
    with pytest.raises((AttributeError, TypeError)):
        ref.cid = "other"  # ty: ignore[invalid-assignment]
