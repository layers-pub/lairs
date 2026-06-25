"""The record-type registry: a map from collection NSID to its model class.

The browser needs to decode any ``pub.layers.*`` record into a typed model, and
to present record types in a stable, readable order grouped by namespace. This
module is the single source of both. ``RECORD_MODELS`` is exhaustive over the
record (not method or permission-set) lexicons; a test cross-checks it against
the generated modules so it cannot silently drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.records._generated import (
    alignment,
    annotation,
    changelog,
    corpus,
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

if TYPE_CHECKING:
    import didactic.api as dx

__all__ = ["RECORD_MODELS", "label_of", "namespace_of"]

# every pub.layers.* record type, mapped to its generated model class.
RECORD_MODELS: dict[str, type[dx.Model]] = {
    "pub.layers.corpus.corpus": corpus.Corpus,
    "pub.layers.corpus.membership": corpus.Membership,
    "pub.layers.expression.expression": expression.Expression,
    "pub.layers.segmentation.segmentation": segmentation.Segmentation,
    "pub.layers.annotation.annotationLayer": annotation.AnnotationLayer,
    "pub.layers.annotation.clusterSet": annotation.ClusterSet,
    "pub.layers.alignment.alignment": alignment.Alignment,
    "pub.layers.ontology.ontology": ontology.Ontology,
    "pub.layers.ontology.typeDef": ontology.TypeDef,
    "pub.layers.resource.collection": resource.Collection,
    "pub.layers.resource.collectionMembership": resource.CollectionMembership,
    "pub.layers.resource.entry": resource.Entry,
    "pub.layers.resource.template": resource.Template,
    "pub.layers.resource.templateComposition": resource.TemplateComposition,
    "pub.layers.resource.filling": resource.Filling,
    "pub.layers.judgment.experimentDef": judgment.ExperimentDef,
    "pub.layers.judgment.judgmentSet": judgment.JudgmentSet,
    "pub.layers.judgment.agreementReport": judgment.AgreementReport,
    "pub.layers.graph.graphNode": graph.GraphNode,
    "pub.layers.graph.graphEdge": graph.GraphEdge,
    "pub.layers.graph.graphEdgeSet": graph.GraphEdgeSet,
    "pub.layers.media.media": media.Media,
    "pub.layers.persona.persona": persona.Persona,
    "pub.layers.eprint.eprint": eprint.Eprint,
    "pub.layers.eprint.dataLink": eprint.DataLink,
    "pub.layers.changelog.entry": changelog.Entry,
}


def namespace_of(nsid: str) -> str:
    """Return the namespace segment of a ``pub.layers.<ns>.<record>`` NSID."""
    parts = nsid.split(".")
    minimum_parts = 4
    return parts[2] if len(parts) >= minimum_parts else nsid


def label_of(nsid: str) -> str:
    """Return the short record label (the last dotted segment) of an NSID."""
    return nsid.rsplit(".", 1)[-1]
