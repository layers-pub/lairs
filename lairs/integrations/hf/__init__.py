"""HuggingFace integration: datasets exporter and Hub push/pull.

This package exposes the HuggingFace data-plane integration: the
:class:`~lairs.integrations.hf.datasets.HuggingFaceExporter` (registered under
the ``hf`` entry point) and its export-shape helpers, plus the Hub
push/pull surface and its provenance models. The optional ``datasets`` and
``huggingface_hub`` dependencies (the ``lairs[hf]`` extra) are imported lazily
inside the methods that need them, so importing this package never pulls them in.
"""

from __future__ import annotations

from lairs.integrations.hf.datasets import (
    TASK_TEMPLATES,
    ExportSpec,
    HuggingFaceExporter,
    TaskTemplate,
    hf_features_from,
    task_template_for,
)
from lairs.integrations.hf.hub import (
    ProvenanceBundle,
    dataset_card,
    load_from_hub,
    provenance_bundle,
    push_to_hub,
)

__all__ = [
    "TASK_TEMPLATES",
    "ExportSpec",
    "HuggingFaceExporter",
    "ProvenanceBundle",
    "TaskTemplate",
    "dataset_card",
    "hf_features_from",
    "load_from_hub",
    "provenance_bundle",
    "push_to_hub",
    "task_template_for",
]
