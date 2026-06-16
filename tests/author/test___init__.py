"""Unit tests for the lairs.author package surface."""

from __future__ import annotations

import lairs.author as mod
from lairs.author import builders, publish


def test_all_lists_the_public_surface() -> None:
    assert set(mod.__all__) == {
        "BuildError",
        "LayerBuilder",
        "PendingId",
        "PublishPlan",
        "WriteClient",
        "WriteOp",
        "WriteResult",
        "apply_writes",
        "bbox",
        "collection_of",
        "keyframe",
        "new_uuid",
        "order_writes",
        "pull",
        "reference",
        "span",
        "spatio_temporal",
        "temporal",
        "token_ref",
    }


def test_every_exported_name_resolves() -> None:
    for name in mod.__all__:
        assert hasattr(mod, name), name


def test_submodules_are_not_shadowed_by_reexports() -> None:
    # the ``publish`` function is intentionally not re-exported at package
    # level so ``from lairs.author import publish`` resolves to the submodule.
    assert builders.span is mod.span
    assert callable(publish.publish)
