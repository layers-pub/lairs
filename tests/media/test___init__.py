"""Unit tests for the lairs.media package surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

import lairs.media as mod

if TYPE_CHECKING:
    from collections.abc import Callable


def test_public_surface() -> None:
    assert set(mod.__all__) == {
        "AnchorTarget",
        "BlobCache",
        "BlobFetcher",
        "MediaHandle",
        "UriFetcher",
        "resolve_anchor",
        "resolve_media",
    }


def test_importing_media_does_not_import_heavy_decoders(
    assert_lazy_import: Callable[..., None],
) -> None:
    # importing the package must never pull in an optional decoder
    assert_lazy_import(
        "lairs.media",
        "soundfile",
        "av",
        "mne",
        "librosa",
        "decord",
    )
