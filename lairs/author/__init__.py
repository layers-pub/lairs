"""Ergonomic record authoring and bulk publishing.

Builders over the generated models plus the local-VCS-to-PDS publish workflow.
The builders (:mod:`lairs.author.builders`) construct anchors, annotation
layers, and cross-references over the generated models; the publish path
(:mod:`lairs.author.publish`) carries the write client, dependency-ordered bulk
``applyWrites``, and the Repository-to-PDS diff.
"""

from __future__ import annotations

from lairs.author.builders import (
    BuildError,
    LayerBuilder,
    PendingId,
    bbox,
    keyframe,
    new_uuid,
    reference,
    span,
    spatio_temporal,
    temporal,
    token_ref,
)
from lairs.author.publish import (
    PublishPlan,
    WriteClient,
    WriteOp,
    WriteResult,
    apply_writes,
    collection_of,
    order_writes,
    pull,
)

# the ``publish`` and ``builders`` submodules are intentionally not re-exported
# as package-level names: a same-named symbol would shadow the submodule and
# break ``from lairs.author import publish``. The publish entry point is reached
# as ``lairs.author.publish.publish`` (or via the data layer's Corpus.publish).
__all__ = [
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
]
