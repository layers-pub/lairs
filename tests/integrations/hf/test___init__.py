"""Unit tests for the lairs.integrations.hf package surface."""

from __future__ import annotations

import sys

import lairs.integrations.hf as mod


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


def test_importing_package_does_not_import_optional_deps() -> None:
    # importing the package must never pull in the optional lairs[hf] extras.
    for name in list(sys.modules):
        if name == "datasets" or name.startswith("datasets."):
            sys.modules.pop(name, None)
        if name == "huggingface_hub" or name.startswith("huggingface_hub."):
            sys.modules.pop(name, None)
    importlib_module = __import__("importlib")
    importlib_module.reload(mod)
    assert "datasets" not in sys.modules
    assert "huggingface_hub" not in sys.modules
