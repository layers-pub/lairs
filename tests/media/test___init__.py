"""Unit tests for the lairs.media package surface."""

from __future__ import annotations

import sys

import lairs.media as mod


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


def test_importing_media_does_not_import_heavy_decoders() -> None:
    # importing the package must never pull in an optional decoder
    for heavy in ("soundfile", "av", "mne", "librosa", "decord"):
        assert heavy not in sys.modules
