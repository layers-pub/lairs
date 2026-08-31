"""Dataset discovery for the Layers network.

Composes identity resolution, the PDS and appview clients, and the panproto
store into a discovery surface: list a single actor's datasets and repository
table of contents (Tier 1), fan out over a seed of actors and resolve
cross-repo, ref-anchored link queries (Tier 2), and build a local, searchable
index from the firehose and a backfill crawl (Tier 3).
"""

from __future__ import annotations

from lairs.discovery.actor import list_datasets, table_of_contents
from lairs.discovery.cards import (
    CollectionCard,
    CrawlReport,
    DatasetCard,
    MutedDataset,
)
from lairs.discovery.collections import list_collections
from lairs.discovery.federated import datasets_using_ontology, discover_datasets
from lairs.discovery.index import CardDiff, DiscoveryIndex, default_index_path
from lairs.discovery.ingest import (
    build_index,
    discover,
    discover_collections,
    update_index,
)
from lairs.discovery.links import (
    Rollup,
    containers_of,
    datasets_for_eprint,
    members_of_collection,
    members_of_corpus,
    rollup_of_collection,
)
from lairs.discovery.models import (
    CollectionCount,
    CollectionFilter,
    CollectionSummary,
    DatasetFilter,
    DatasetSummary,
    RepoTableOfContents,
)
from lairs.discovery.query import (
    CollectionHit,
    SearchHit,
    SearchQuery,
    search,
    search_collections,
)
from lairs.discovery.sources import (
    Source,
    UnknownSourceError,
    default_source,
    default_sources_path,
    load_sources,
    resolve_source,
)

__all__ = [
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
]
