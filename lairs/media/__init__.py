"""Modality tooling: audio, video, and neural anchor-aware slicing.

This package resolves a media record (blob or external URI) to a decoded handle
and slices a decoded target by a Layers anchor. Importing the package, and any
of its submodules, never imports a heavy optional decoder (``soundfile``,
``av``, ``mne``); those are imported lazily inside the decode functions and
raise an actionable error when their extra is missing.
"""

from __future__ import annotations

from lairs.media.anchors import AnchorTarget, resolve_anchor
from lairs.media.resolve import (
    BlobCache,
    BlobFetcher,
    MediaHandle,
    UriFetcher,
    resolve_media,
)

__all__ = [
    "AnchorTarget",
    "BlobCache",
    "BlobFetcher",
    "MediaHandle",
    "UriFetcher",
    "resolve_anchor",
    "resolve_media",
]
