"""Unit tests for lairs.records.blobref."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("didactic")

import didactic.api as dx

from lairs.atproto.pds import RecordEnvelope, decode
from lairs.records._generated import media
from lairs.records.blobref import BlobRef, normalize_blob_refs

if TYPE_CHECKING:
    from lairs._types import JsonValue


def test_blobref_is_didactic_model() -> None:
    assert issubclass(BlobRef, dx.Model)


def test_normalize_blob_refs_rewrites_wire_form() -> None:
    """An ATProto blob wire object becomes BlobRef-shaped, nested ones too."""
    wire: JsonValue = {
        "kind": "audio",
        "blob": {
            "$type": "blob",
            "ref": {"$link": "bafkreiabc"},
            "mimeType": "audio/wav",
            "size": 4096,
        },
        "items": [{"b": {"$type": "blob", "ref": {"$link": "bafkre2"}}}],
    }
    out = normalize_blob_refs(wire)
    assert isinstance(out, dict)
    assert out["blob"] == {"cid": "bafkreiabc", "mime_type": "audio/wav", "size": 4096}
    items = out["items"]
    assert isinstance(items, list)
    nested = items[0]
    assert isinstance(nested, dict)
    assert nested["b"] == {"cid": "bafkre2", "mime_type": None, "size": None}
    assert out["kind"] == "audio"


def test_normalize_blob_refs_passes_through_non_blobs() -> None:
    """Plain values and non-blob dicts are returned unchanged."""
    assert normalize_blob_refs({"a": 1, "b": ["x", None]}) == {"a": 1, "b": ["x", None]}
    assert normalize_blob_refs("text") == "text"
    # a dict that merely names $type but is not a blob ref is untouched.
    assert normalize_blob_refs({"$type": "other", "x": 1}) == {"$type": "other", "x": 1}


def test_blob_record_round_trips_through_decode() -> None:
    """A PDS-wire blob record decodes back into its model's BlobRef field."""
    value: JsonValue = {
        "$type": "pub.layers.media.media",
        "kind": "audio",
        "createdAt": "2026-06-18T00:00:00Z",
        "mimeType": "audio/wav",
        "blob": {
            "$type": "blob",
            "ref": {"$link": "bafkreiabc"},
            "mimeType": "audio/wav",
            "size": 4096,
        },
    }
    envelope = RecordEnvelope(
        uri="at://did:plc:x/pub.layers.media.media/m1", cid="bafy", value=value
    )
    record = decode(envelope, media.Media)
    assert isinstance(record.blob, BlobRef)
    assert record.blob.cid == "bafkreiabc"
    assert record.blob.mime_type == "audio/wav"
    assert record.blob.size == 4096


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
