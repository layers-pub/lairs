"""Unit tests for the lairs.integrations.hf package surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

import lairs.integrations.hf as mod

if TYPE_CHECKING:
    from collections.abc import Callable


def test_public_surface() -> None:
    assert set(mod.__all__) == {
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
    }


def test_all_names_are_resolvable() -> None:
    for name in mod.__all__:
        assert hasattr(mod, name)


def test_importing_package_does_not_import_optional_deps(
    assert_lazy_import: Callable[..., None],
) -> None:
    # importing the package must never pull in the optional lairs[hf] extras.
    assert_lazy_import(
        "lairs.integrations.hf",
        "datasets",
        "huggingface_hub",
    )
