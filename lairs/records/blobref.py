"""Blob reference value type.

A ``BlobRef`` is the lairs representation of an ATProto blob: a content
identifier plus optional metadata. Blob bytes are never inlined into a record;
they are fetched on demand through the media layer and cached by content
identifier. ``BlobRef`` is a didactic model, like every other structured value
in lairs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from lairs._types import JsonValue

__all__ = ["BlobRef", "normalize_blob_refs"]


class BlobRef(dx.Model):
    """An immutable reference to an ATProto blob.

    Attributes
    ----------
    cid : str
        The content identifier of the blob.
    mime_type : str or None, optional
        The MIME type of the blob, when known.
    size : int or None, optional
        The size of the blob in bytes, when known.
    """

    cid: str = dx.field(description="content identifier of the blob")
    mime_type: str | None = dx.field(
        default=None,
        description="MIME type of the blob, when known",
    )
    size: int | None = dx.field(
        default=None,
        description="size of the blob in bytes, when known",
    )


def normalize_blob_refs(value: JsonValue) -> JsonValue:
    """Rewrite ATProto blob wire objects into :class:`BlobRef` shape, recursively.

    A blob arrives from a PDS in ATProto wire form,
    ``{"$type": "blob", "ref": {"$link": <cid>}, "mimeType": <str>, "size": <int>}``,
    whereas :class:`BlobRef` declares ``cid``/``mime_type``/``size``. Each such
    object found anywhere in a record value is rewritten so the record's blob
    fields validate; every other mapping and list is walked recursively and all
    other values pass through unchanged. This makes a published record decode
    back into its model on the read path, completing the blob round trip.

    Parameters
    ----------
    value : lairs._types.JsonValue
        A record value (or any nested fragment of one) decoded from the wire.

    Returns
    -------
    lairs._types.JsonValue
        The value with every ATProto blob object rewritten to ``BlobRef`` shape.
    """
    if isinstance(value, dict):
        ref = value.get("ref")
        if value.get("$type") == "blob" and isinstance(ref, dict):
            link = ref.get("$link")
            if isinstance(link, str):
                return {
                    "cid": link,
                    "mime_type": value.get("mimeType"),
                    "size": value.get("size"),
                }
        return {key: normalize_blob_refs(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_blob_refs(item) for item in value]
    return value
