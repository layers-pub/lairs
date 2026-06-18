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
        "RepoTableOfContents",
        "SearchHit",
        "SearchQuery",
        "build_index",
        "datasets_for_eprint",
        "datasets_using_ontology",
        "discover_datasets",
        "list_datasets",
        "members_of_corpus",
        "search",
        "table_of_contents",
        "update_index",
    }
