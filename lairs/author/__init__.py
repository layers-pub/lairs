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
from lairs.author.changelog import (
    BumpClassifier,
    BumpLevel,
    ComponentChange,
    DefaultBumpClassifier,
    FieldChange,
    FieldDiff,
    build_aggregate_entry,
    build_entry,
    bump_version,
    diff_fields,
    diff_record,
    generate_changelog,
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

# the ``publish``, ``builders``, and ``changelog`` submodules are intentionally
# not re-exported as package-level names: a same-named symbol would shadow the
# submodule and break ``from lairs.author import publish``. The publish entry
# point is reached as ``lairs.author.publish.publish`` (or via the data layer's
# Corpus.publish); the changelog generators are re-exported by function name.
__all__ = [
    "BuildError",
    "BumpClassifier",
    "BumpLevel",
    "ComponentChange",
    "DefaultBumpClassifier",
    "FieldChange",
    "FieldDiff",
    "LayerBuilder",
    "PendingId",
    "PublishPlan",
    "WriteClient",
    "WriteOp",
    "WriteResult",
    "apply_writes",
    "bbox",
    "build_aggregate_entry",
    "build_entry",
    "bump_version",
    "collection_of",
    "diff_fields",
    "diff_record",
    "generate_changelog",
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
