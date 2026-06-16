"""HuggingFace-like dataset and corpus API.

This package exposes the dataset-and-corpus surface over the generated record
models: :class:`~lairs.data.dataset.Dataset` (a lazy, optionally streaming
sequence of one model type), :class:`~lairs.data.corpus.Corpus` (a graph of
records joined by AT-URI), :func:`~lairs.data.corpus.load_corpus`, and the
feature-description models in :mod:`lairs.data.features`. Importing this package
never requires the optional pandas dependency.
"""

from __future__ import annotations

from lairs.data.corpus import (
    Corpus,
    ExpressionWithAnnotations,
    ExpressionWithMedia,
    ExpressionWithSegmentation,
    load_corpus,
)
from lairs.data.dataset import Dataset
from lairs.data.features import Features, FeatureSpec, dtype_of, features_of

__all__ = [
    "Corpus",
    "Dataset",
    "ExpressionWithAnnotations",
    "ExpressionWithMedia",
    "ExpressionWithSegmentation",
    "FeatureSpec",
    "Features",
    "dtype_of",
    "features_of",
    "load_corpus",
]
