"""Tests for the lairs.discovery package surface."""

from __future__ import annotations

from lairs import discovery


def test_exports() -> None:
    assert set(discovery.__all__) == {
        "CardDiff",
        "CollectionCount",
        "CrawlReport",
        "DatasetCard",
        "DatasetFilter",
        "DatasetSummary",
        "DiscoveryIndex",
        "MutedDataset",
        "RepoTableOfContents",
        "SearchHit",
        "SearchQuery",
        "Source",
        "UnknownSourceError",
        "build_index",
        "datasets_for_eprint",
        "datasets_using_ontology",
        "default_index_path",
        "default_sources_path",
        "discover",
        "discover_datasets",
        "list_datasets",
        "load_sources",
        "members_of_corpus",
        "resolve_source",
        "search",
        "table_of_contents",
        "update_index",
    }
