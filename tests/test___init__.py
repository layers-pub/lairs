"""Unit tests for the lairs top-level package."""

from __future__ import annotations

import pytest

import lairs
from lairs.integrations.registry import UnknownAdapterError
from lairs.records.blobref import BlobRef


def test_version() -> None:
    assert isinstance(lairs.__version__, str)


def test_public_surface() -> None:
    assert set(lairs.__all__) == {
        "BlobRef",
        "__version__",
        "codec",
        "exporter",
        "knowledge_base",
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
