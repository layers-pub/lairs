"""Media resolution: a media record resolves to a decoded handle.

``resolve_media`` dispatches on blob versus external URI, fetches lazily, and
caches by content identifier. The returned ``MediaHandle`` is a didactic model
that carries the raw bytes in an opaque field with typed metadata alongside.
"""

from __future__ import annotations

import didactic.api as dx

__all__ = ["MediaHandle", "resolve_media"]


class MediaHandle(dx.Model):
    """A resolved media handle holding raw bytes and typed metadata.

    The raw media bytes live in an opaque field; the modality, MIME type, and
    duration are typed metadata so callers never inspect the payload blindly.

    Parameters
    ----------
    cid : str
        The content identifier of the resolved media.
    mime_type : str
        The MIME type of the media.
    modality : str
        The modality (``audio``, ``video``, ``image``, or ``document``).
    duration_ms : int or None, optional
        The media duration in milliseconds, when known.
    data : bytes, optional
        The raw media bytes, carried as an opaque payload.
    """

    cid: str = dx.field(description="content identifier of the media")
    mime_type: str = dx.field(description="MIME type of the media")
    modality: str = dx.field(description="media modality token")
    duration_ms: int | None = dx.field(
        default=None,
        description="media duration in milliseconds, when known",
    )
    data: bytes = dx.field(
        default=b"",
        opaque=True,
        description="raw media bytes carried as an opaque payload",
    )


def resolve_media(media: dx.Model) -> MediaHandle:
    """Resolve a media record to a decoded media handle.

    Parameters
    ----------
    media : didactic.Model
        A ``media.media`` record instance.

    Returns
    -------
    MediaHandle
        The resolved handle (bytes are fetched lazily on first decode).

    Raises
    ------
    NotImplementedError
        Always, until the media layer lands.
    """
    raise NotImplementedError
