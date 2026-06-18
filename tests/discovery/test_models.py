"""Unit tests for lairs.discovery.models."""

from __future__ import annotations

from lairs.discovery import models
from lairs.discovery.models import (
    CollectionCount,
    DatasetFilter,
    DatasetSummary,
    RepoTableOfContents,
)

_URI = "at://did:plc:x/pub.layers.corpus.corpus/a"


def test_exports() -> None:
    assert set(models.__all__) == {
        "CollectionCount",
        "DatasetFilter",
        "DatasetSummary",
        "RepoTableOfContents",
    }


def test_dataset_summary_defaults() -> None:
    summary = DatasetSummary(uri=_URI, did="did:plc:x", name="demo")
    assert summary.languages == ()
    assert summary.ontology_refs == ()
    assert summary.has_adjudication is False
    assert summary.description is None


def test_dataset_summary_round_trips() -> None:
    summary = DatasetSummary(
        uri=_URI,
        did="did:plc:x",
        name="demo",
        languages=("en", "de"),
        expression_count=12,
        has_adjudication=True,
    )
    restored = DatasetSummary.model_validate_json(summary.model_dump_json())
    assert restored == summary


def test_repo_table_of_contents_embeds_counts() -> None:
    toc = RepoTableOfContents(
        did="did:plc:x",
        collections=(
            CollectionCount(
                nsid="pub.layers.corpus.corpus",
                count=3,
                is_dataset_like=True,
            ),
            CollectionCount(nsid="app.bsky.feed.post", count=9),
        ),
        dataset_collections=("pub.layers.corpus.corpus",),
    )
    restored = RepoTableOfContents.model_validate_json(toc.model_dump_json())
    assert restored == toc
    assert restored.collections[0].count == 3
    assert restored.collections[1].is_dataset_like is False


def test_dataset_filter_defaults_none() -> None:
    flt = DatasetFilter()
    assert flt.language is None
    assert flt.has_adjudication is None
