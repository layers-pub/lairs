"""Index record models and the corpus-to-card builder.

The discovery index stores these ``dx.Model`` records in a panproto Repository:
a ``DatasetCard`` per discovered corpus (a denormalized, searchable summary with
provenance and freshness), a ``SyncCursor`` per firehose relay, and a
``RepoCrawlState`` per crawled repository. These are client-side index
bookkeeping under a local ``lairs.index.*`` namespace, never published Layers
records and never code-generated.
"""

from __future__ import annotations

import hashlib
from datetime import datetime  # noqa: TC003  (runtime: didactic field classification)
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.discovery.models import (  # noqa: TC001  (runtime: didactic field sort)
    DatasetSummary,
)
from lairs.discovery.summary import summary_from_corpus

if TYPE_CHECKING:
    from lairs.records._generated import corpus as corpus_records

__all__ = [
    "CARD_NSID",
    "CRAWL_STATE_NSID",
    "CURSOR_NSID",
    "INDEX_DID",
    "MUTED_NSID",
    "CardFreshness",
    "CardProvenance",
    "CrawlReport",
    "DatasetCard",
    "MutedDataset",
    "RepoCrawlState",
    "SyncCursor",
    "card_from_corpus",
    "card_uri",
]

INDEX_DID = "did:lairs:index"
"""The sentinel authority for the local discovery index's records."""

CARD_NSID = "lairs.index.datasetCard"
"""The collection NSID for dataset cards in the local index."""

CURSOR_NSID = "lairs.index.syncCursor"
"""The collection NSID for firehose sync cursors in the local index."""

CRAWL_STATE_NSID = "lairs.index.repoCrawlState"
"""The collection NSID for per-repo crawl state in the local index."""

MUTED_NSID = "lairs.index.mutedDataset"
"""The collection NSID for permanently muted datasets in the local index."""

_RKEY_LENGTH = 24
"""The hex digest length used for synthetic, deterministic index record keys."""


class CardProvenance(dx.Model):
    """Where a dataset card came from, for trust and refresh.

    Attributes
    ----------
    source_did : str
        The corpus author's DID.
    source_endpoint : str
        The PDS or appview base URL the card was read from.
    discovered_via : str
        How the card entered the index (``"firehose"``, ``"crawl"``, ``"seed"``).
    source_handle : str or None
        The author's handle at discovery time, when known.
    """

    source_did: str = dx.field(description="corpus author DID")
    source_endpoint: str = dx.field(description="PDS or appview base URL")
    discovered_via: str = dx.field(
        description="how the card entered the index (firehose, crawl, seed)",
    )
    source_handle: str | None = dx.field(
        default=None,
        description="author handle at discovery time, when known",
    )


class CardFreshness(dx.Model):
    """Firehose and crawl bookkeeping so freshness and resume are first-class.

    Attributes
    ----------
    first_seen_at : datetime
        When this corpus first entered the index.
    last_updated_at : datetime
        When the card content last changed.
    last_seen_seq : int or None
        The last firehose sequence number that touched the corpus.
    last_seen_rev : str or None
        The last repository commit revision observed for the corpus.
    record_cid : str or None
        The CID of the corpus record at the last refresh.
    """

    first_seen_at: datetime = dx.field(description="when the corpus first entered")
    last_updated_at: datetime = dx.field(description="when the card last changed")
    last_seen_seq: int | None = dx.field(
        default=None,
        description="last firehose sequence number that touched the corpus",
    )
    last_seen_rev: str | None = dx.field(
        default=None,
        description="last repository commit revision observed",
    )
    record_cid: str | None = dx.field(
        default=None,
        description="CID of the corpus record at the last refresh",
    )


class DatasetCard(dx.Model):
    """A searchable, denormalized index entry for one corpus.

    Attributes
    ----------
    summary : DatasetSummary
        The corpus-derived listing projection.
    provenance : CardProvenance
        Where the card came from.
    freshness : CardFreshness
        First-seen and last-updated bookkeeping.
    annotation_rounds : int or None
        The number of annotation rounds declared, when present.
    adjudication_method : str or None
        The adjudication method slug, when present.
    redundancy_count : int or None
        The declared annotator redundancy, when present.
    quality_metrics : tuple of str
        The quality-criterion metric slugs declared for the corpus.
    """

    summary: dx.Embed[DatasetSummary] = dx.field(description="corpus listing summary")
    provenance: dx.Embed[CardProvenance] = dx.field(description="card provenance")
    freshness: dx.Embed[CardFreshness] = dx.field(description="card freshness")
    annotation_rounds: int | None = dx.field(
        default=None,
        description="number of annotation rounds declared",
    )
    adjudication_method: str | None = dx.field(
        default=None,
        description="adjudication method slug",
    )
    redundancy_count: int | None = dx.field(
        default=None,
        description="declared annotator redundancy",
    )
    quality_metrics: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="quality-criterion metric slugs",
    )


class SyncCursor(dx.Model):
    """A resumable firehose position for one relay.

    Attributes
    ----------
    relay : str
        The firehose endpoint this cursor is for.
    seq : int
        The last fully-processed firehose sequence number.
    updated_at : datetime
        When the cursor was last written.
    """

    relay: str = dx.field(description="firehose endpoint")
    seq: int = dx.field(description="last fully-processed firehose sequence number")
    updated_at: datetime = dx.field(description="when the cursor was last written")


class RepoCrawlState(dx.Model):
    """Per-repository crawl bookkeeping so a re-run skips finished repos.

    Attributes
    ----------
    did : str
        The crawled repository DID.
    endpoint : str
        The PDS endpoint the repo was crawled from.
    has_layers_corpus : bool
        Whether the repo carried the corpus collection.
    corpora_found : int
        The number of corpora indexed from the repo.
    last_crawled_at : datetime
        When the repo was last crawled.
    repos_cursor : str or None
        A ``listRepos`` pagination checkpoint, when crawling a relay.
    """

    did: str = dx.field(description="crawled repository DID")
    endpoint: str = dx.field(description="PDS endpoint the repo was crawled from")
    has_layers_corpus: bool = dx.field(
        default=False,
        description="whether the repo carried the corpus collection",
    )
    corpora_found: int = dx.field(
        default=0,
        description="number of corpora indexed from the repo",
    )
    last_crawled_at: datetime | None = dx.field(
        default=None,
        description="when the repo was last crawled",
    )
    repos_cursor: str | None = dx.field(
        default=None,
        description="listRepos pagination checkpoint, when crawling a relay",
    )


class MutedDataset(dx.Model):
    """A permanently muted dataset the index must not auto-index.

    A mute is self-describing so it can be listed and unmuted offline without a
    re-crawl: it keeps the corpus AT-URI, a display name, and the source it came
    from, plus when it was muted.

    Attributes
    ----------
    uri : str
        The muted corpus AT-URI.
    name : str
        The dataset's display name at mute time.
    source_endpoint : str
        The endpoint the dataset was discovered from.
    muted_at : datetime
        When the dataset was muted.
    """

    uri: str = dx.field(description="the muted corpus AT-URI")
    name: str = dx.field(description="the dataset's display name at mute time")
    source_endpoint: str = dx.field(
        description="the endpoint the dataset was discovered from",
    )
    muted_at: datetime = dx.field(description="when the dataset was muted")


class CrawlReport(dx.Model):
    """A summary of a crawl or firehose pass, logging every skip.

    Attributes
    ----------
    repos_seen : int
        The number of repositories visited.
    repos_with_corpora : int
        The number of repositories that held a corpus collection.
    cards_built : int
        The number of cards built or refreshed.
    cards_unchanged : int
        The number of cards that were already current (dedup hits).
    cards_removed : int
        The number of cards removed in response to a corpus-deletion commit.
    skipped : tuple of str
        Human-readable skip reasons, including any bound that was hit.
    revision : str or None
        The commit revision the pass produced, when any.
    """

    repos_seen: int = dx.field(default=0, description="repositories visited")
    repos_with_corpora: int = dx.field(
        default=0,
        description="repositories that held a corpus collection",
    )
    cards_built: int = dx.field(default=0, description="cards built or refreshed")
    cards_unchanged: int = dx.field(
        default=0,
        description="cards already current (dedup hits)",
    )
    cards_removed: int = dx.field(
        default=0,
        description="cards removed in response to a corpus-deletion commit",
    )
    skipped: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="human-readable skip reasons, including bounds hit",
    )
    revision: str | None = dx.field(
        default=None,
        description="commit revision the pass produced",
    )


def card_uri(corpus_uri: str) -> str:
    """Build the deterministic index AT-URI for a corpus's card.

    The same corpus always maps to the same card key, so re-indexing is
    idempotent and content-addressed dedup falls out for free.

    Parameters
    ----------
    corpus_uri : str
        The corpus AT-URI.

    Returns
    -------
    str
        The card's index AT-URI under the local ``lairs.index.*`` namespace.
    """
    digest = hashlib.sha256(corpus_uri.encode("utf-8")).hexdigest()[:_RKEY_LENGTH]
    return f"at://{INDEX_DID}/{CARD_NSID}/{digest}"


def card_from_corpus(
    corpus_uri: str,
    corpus: corpus_records.Corpus,
    *,
    provenance: CardProvenance,
    freshness: CardFreshness,
) -> DatasetCard:
    """Build a ``DatasetCard`` from a discovered corpus and its provenance.

    Parameters
    ----------
    corpus_uri : str
        The corpus AT-URI.
    corpus : lairs.records._generated.corpus.Corpus
        The discovered corpus record.
    provenance : CardProvenance
        Where the corpus was discovered.
    freshness : CardFreshness
        First-seen and last-updated bookkeeping for the card.

    Returns
    -------
    DatasetCard
        The denormalized index card.
    """
    summary = summary_from_corpus(
        corpus,
        uri=corpus_uri,
        did=provenance.source_did,
        handle=provenance.source_handle,
        source_endpoint=provenance.source_endpoint,
    )
    design = corpus.annotationDesign
    rounds = design.annotationRounds if design is not None else None
    method = (
        design.adjudication.method
        if design is not None and design.adjudication is not None
        else None
    )
    redundancy = (
        design.redundancy.count
        if design is not None and design.redundancy is not None
        else None
    )
    criteria = design.qualityCriteria if design is not None else None
    metrics = tuple(item.metric for item in criteria) if criteria else ()
    return DatasetCard(
        summary=summary,
        provenance=provenance,
        freshness=freshness,
        annotation_rounds=rounds,
        adjudication_method=method,
        redundancy_count=redundancy,
        quality_metrics=metrics,
    )
