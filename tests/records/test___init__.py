"""Unit tests for the lairs.records package surface."""

from __future__ import annotations

import didactic.api as dx

from lairs import records
from lairs.records.blobref import BlobRef

_NAMESPACES = (
    "alignment",
    "annotation",
    "changelog",
    "corpus",
    "defs",
    "eprint",
    "expression",
    "graph",
    "judgment",
    "media",
    "ontology",
    "persona",
    "resource",
    "segmentation",
)


def test_exports() -> None:
    expected = {
        "BlobRef",
        "anchor_kind",
        "explode_layer",
        "views",
        *_NAMESPACES,
    }
    assert set(records.__all__) == expected


def test_blobref_reexport() -> None:
    assert records.BlobRef is BlobRef


def test_namespace_modules_are_present() -> None:
    for namespace in _NAMESPACES:
        assert hasattr(records, namespace)


def test_record_classes_are_models() -> None:
    assert issubclass(records.expression.Expression, dx.Model)
    assert issubclass(records.defs.Span, dx.Model)


def test_union_is_a_tagged_union() -> None:
    selector = records.defs.ExternalTargetSelector
    assert issubclass(selector, dx.TaggedUnion)
    assert selector.__discriminator__ == "kind"
