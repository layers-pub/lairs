"""Generated record models and generated-safe view helpers.

The generated ``dx.Model`` modules live under :mod:`lairs.records._generated`,
one module per ``pub.layers.*`` namespace. This package re-exports those
namespace modules together with hand-written behaviour over the generated
models: :class:`~lairs.records.blobref.BlobRef` and the view helpers in
:mod:`lairs.records.views`.

The namespace modules are accessed as attributes (for example
``lairs.records.expression.Expression`` or ``lairs.records.defs.Anchor``); the
record classes themselves are generated and must not be hand-edited.
"""

from __future__ import annotations

from lairs.records import views
from lairs.records._generated import (
    alignment,
    annotation,
    changelog,
    corpus,
    defs,
    eprint,
    expression,
    graph,
    judgment,
    media,
    ontology,
    persona,
    resource,
    segmentation,
)
from lairs.records.blobref import BlobRef
from lairs.records.views import anchor_kind, explode_layer

__all__ = [
    "BlobRef",
    "alignment",
    "anchor_kind",
    "annotation",
    "changelog",
    "corpus",
    "defs",
    "eprint",
    "explode_layer",
    "expression",
    "graph",
    "judgment",
    "media",
    "ontology",
    "persona",
    "resource",
    "segmentation",
    "views",
]
