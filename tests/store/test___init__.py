"""Unit tests for the lairs.store package surface."""

from __future__ import annotations

import lairs.store as mod


def test_all_exports_the_public_surface() -> None:
    assert set(mod.__all__) == {
        "BlobCache",
        "BlobCacheError",
        "ModelPool",
        "RecordDiff",
        "Repository",
        "Workspace",
        "annotations_table",
        "expressions_table",
        "flatten_anchor",
        "materialize",
        "records_to_table",
    }


def test_every_exported_name_is_importable() -> None:
    for name in mod.__all__:
        assert hasattr(mod, name)
