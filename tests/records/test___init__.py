"""Unit tests for the lairs.records package surface."""

from __future__ import annotations

from lairs import records
from lairs.records.blobref import BlobRef


def test_exports() -> None:
    assert set(records.__all__) == {"BlobRef"}


def test_blobref_reexport() -> None:
    assert records.BlobRef is BlobRef
