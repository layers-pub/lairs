"""HuggingFace-like dataset and corpus API.

This package exposes the dataset-and-corpus surface over the generated record
models: :class:`~lairs.data.dataset.Dataset` (a lazy, optionally streaming
sequence of one model type), :class:`~lairs.data.corpus.Corpus` (a graph of
records joined by AT-URI), :func:`~lairs.data.corpus.load_corpus`, and the
feature-description models in :mod:`lairs.data.features`. Importing this package
never requires the optional pandas dependency.
"""

from __future__ import annotations

from lairs.data.acquisition import (
    Acquisition,
    SessionWithMedia,
    SessionWithParticipants,
    load_acquisition,
)
from lairs.data.collection import Collection, load_collection
from lairs.data.corpus import (
    Corpus,
    ExpressionWithAnnotations,
    ExpressionWithMedia,
    ExpressionWithSegmentation,
    load_corpus,
)
from lairs.data.dataset import Dataset
from lairs.data.features import Features, FeatureSpec, dtype_of, features_of
from lairs.data.judgment import (
    ItemDistribution,
    JudgmentRow,
    JudgmentStudy,
    LabelCount,
    Participant,
    ParticipantSummary,
    RegionResponseRow,
    load_judgment_study,
)
from lairs.data.media import media_by_kind, signal_media

__all__ = [
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
]
