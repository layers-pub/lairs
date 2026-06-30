"""Dataset discovery for the Layers network.

Composes identity resolution, the PDS and appview clients, and the panproto
store into a discovery surface: list a single actor's datasets and repository
table of contents (Tier 1), fan out over a seed of actors and resolve
cross-repo, ref-anchored link queries (Tier 2), and build a local, searchable
index from the firehose and a backfill crawl (Tier 3).
"""

from __future__ import annotations

from lairs.discovery.actor import list_datasets, table_of_contents
from lairs.discovery.cards import CrawlReport, DatasetCard, MutedDataset
from lairs.discovery.federated import datasets_using_ontology, discover_datasets
from lairs.discovery.index import CardDiff, DiscoveryIndex, default_index_path
from lairs.discovery.ingest import build_index, discover, update_index
from lairs.discovery.links import datasets_for_eprint, members_of_corpus
from lairs.discovery.models import (
    CollectionCount,
    DatasetFilter,
    DatasetSummary,
    RepoTableOfContents,
)
from lairs.discovery.query import SearchHit, SearchQuery, search
from lairs.discovery.sources import (
    Source,
    UnknownSourceError,
    default_sources_path,
    load_sources,
    resolve_source,
)

__all__ = [
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
]
