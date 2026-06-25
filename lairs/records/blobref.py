"""Blob reference value type.

A ``BlobRef`` is the lairs representation of an ATProto blob: a content
identifier plus optional metadata. Blob bytes are never inlined into a record;
they are fetched on demand through the media layer and cached by content
identifier. ``BlobRef`` is a didactic model, like every other structured value
in lairs.
"""

from __future__ import annotations

import didactic.api as dx

__all__ = ["BlobRef"]


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
