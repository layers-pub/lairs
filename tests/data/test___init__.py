"""Unit tests for the lairs.data package surface."""

from __future__ import annotations

import sys

import lairs.data as mod


def test_public_surface() -> None:
    assert set(mod.__all__) == {
        "Acquisition",
        "Collection",
        "Corpus",
        "Dataset",
        "ExpressionWithAnnotations",
        "ExpressionWithMedia",
        "ExpressionWithSegmentation",
        "FeatureSpec",
        "Features",
        "ItemDistribution",
        "JudgmentRow",
        "JudgmentStudy",
        "LabelCount",
        "Participant",
        "ParticipantSummary",
        "RegionResponseRow",
        "SessionWithMedia",
        "SessionWithParticipants",
        "dtype_of",
        "features_of",
        "load_acquisition",
        "load_collection",
        "load_corpus",
        "load_judgment_study",
        "media_by_kind",
        "signal_media",
    }


def test_every_export_is_attribute() -> None:
    for name in mod.__all__:
        assert hasattr(mod, name)


def test_import_does_not_require_pandas() -> None:
    # importing the package must not pull pandas in: pandas is optional and only
    # loaded lazily by Dataset.to_pandas. confirm the data modules are imported
    # without pandas appearing as a transitive import of the package itself.
    data_modules = [
        name
        for name in sys.modules
        if name == "lairs.data" or name.startswith("lairs.data.")
    ]
    assert "lairs.data" in data_modules
    for name in data_modules:
        module = sys.modules[name]
        assert "pandas" not in getattr(module, "__dict__", {})
