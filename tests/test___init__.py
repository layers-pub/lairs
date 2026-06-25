"""Unit tests for the lairs top-level package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version

import pytest

import lairs
from lairs.integrations.registry import UnknownAdapterError
from lairs.records.blobref import BlobRef


def test_version_matches_distribution_metadata() -> None:
    assert isinstance(lairs.__version__, str)
    try:
        installed = distribution_version("lairs")
    except PackageNotFoundError:
        installed = None
    if installed is not None:
        # __version__ is derived from the installed distribution metadata, so
        # the two can never silently diverge.
        assert lairs.__version__ == installed
    else:
        # In a source tree with no installed distribution the literal fallback
        # is the single source of truth for the release version.
        assert lairs.__version__ == lairs._FALLBACK_VERSION


def test_fallback_version_is_release_target() -> None:
    # The fallback literal is the release version and must stay in step with
    # pyproject.toml's version field.
    assert lairs._FALLBACK_VERSION == "0.1.0"
    parts = lairs._FALLBACK_VERSION.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_public_surface() -> None:
    assert set(lairs.__all__) == {
        "BlobRef",
        "Corpus",
        "DatasetFilter",
        "DatasetSummary",
        "RepoTableOfContents",
        "Session",
        "__version__",
        "authed_client",
        "codec",
        "discover_datasets",
        "exporter",
        "knowledge_base",
        "list_datasets",
        "load_corpus",
        "login",
        "table_of_contents",
    }


def test_blobref_reexport() -> None:
    assert lairs.BlobRef is BlobRef


def test_codec_lookup_unknown() -> None:
    with pytest.raises(UnknownAdapterError):
        lairs.codec("definitely-not-registered-xyz")
    with pytest.raises(UnknownAdapterError):
        lairs.exporter("definitely-not-registered-xyz")
    with pytest.raises(UnknownAdapterError):
        lairs.knowledge_base("definitely-not-registered-xyz")
