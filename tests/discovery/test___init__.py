"""Tests for the lairs.discovery package surface."""

from __future__ import annotations

from lairs import discovery


def test_exports() -> None:
    assert set(discovery.__all__) == {
        "CardDiff",
        "CollectionCard",
        "CollectionCount",
        "CollectionFilter",
        "CollectionHit",
        "CollectionSummary",
        "CrawlReport",
        "DatasetCard",
        "DatasetFilter",
        "DatasetSummary",
        "DiscoveryIndex",
        "MutedDataset",
        "RepoTableOfContents",
        "Rollup",
        "SearchHit",
        "SearchQuery",
        "Source",
        "UnknownSourceError",
        "build_index",
        "containers_of",
        "datasets_for_eprint",
        "datasets_using_ontology",
        "default_index_path",
        "default_source",
        "default_sources_path",
        "discover",
        "discover_collections",
        "discover_datasets",
        "list_collections",
        "list_datasets",
        "load_sources",
        "members_of_collection",
        "members_of_corpus",
        "resolve_source",
        "rollup_of_collection",
        "search",
        "search_collections",
        "table_of_contents",
        "update_index",
    }
