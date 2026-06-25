"""Index ingest pipelines: backfill crawl and firehose tail.

Both pipelines write through the panproto Repository: every discovered corpus
becomes a ``DatasetCard``, and the resumable cursor and per-repo crawl state are
records too, so progress is versioned. Cards are only re-written when their
content changes, preserving content-addressed dedup; bounds and skips are always
logged in the returned ``CrawlReport``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import didactic.api as dx
import httpx

from lairs.atproto.firehose import subscribe_repos
from lairs.discovery.cards import (
    CardFreshness,
    CardProvenance,
    CrawlReport,
    RepoCrawlState,
    SyncCursor,
    card_from_corpus,
)
from lairs.discovery.summary import _CORPUS_NSID, corpus_from_value

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from lairs.atproto.firehose import FirehoseEvent
    from lairs.atproto.pds import RecordEnvelope, RepoDescription
    from lairs.discovery.cards import DatasetCard
    from lairs.discovery.index import DiscoveryIndex

__all__ = ["CorpusLister", "RepoDescriber", "build_index", "update_index"]

_DEFAULT_COMMIT_EVERY = 50
"""How many firehose events to process between cursor checkpoints."""


@runtime_checkable
class RepoDescriber(Protocol):
    """A source of repository descriptions (satisfied by ``PdsClient``)."""

    def describe_repo(self, repo: str) -> RepoDescription:
        """Return the description of a repository."""
        ...


@runtime_checkable
class CorpusLister(Protocol):
    """A source of a repository's records (satisfied by ``PdsClient``)."""

    def list_records(self, repo: str, collection: str) -> Iterator[RecordEnvelope]:
        """Enumerate a repository's records in a collection."""
        ...


def _same_content(existing: DatasetCard, candidate: DatasetCard) -> bool:
    """Return whether two cards carry the same corpus-derived content."""
    return (
        existing.summary == candidate.summary
        and existing.annotation_rounds == candidate.annotation_rounds
        and existing.adjudication_method == candidate.adjudication_method
        and existing.redundancy_count == candidate.redundancy_count
        and existing.quality_metrics == candidate.quality_metrics
    )


def _refresh_card(
    index: DiscoveryIndex,
    card: DatasetCard,
    existing: DatasetCard | None,
) -> bool:
    """Store a card unless its content already matches the indexed one.

    The previously-indexed ``existing`` card is supplied by the caller so the
    index is read once per corpus per pass rather than once here and again in
    :func:`_first_seen`.

    Returns
    -------
    bool
        ``True`` if the card was written (new or changed), ``False`` if the
        indexed card already had the same content.
    """
    if existing is not None and _same_content(existing, card):
        return False
    index.put_card(card)
    return True


def _first_seen(existing: DatasetCard | None, now: datetime) -> datetime:
    """Return the corpus's existing first-seen time, or ``now`` when new."""
    return existing.freshness.first_seen_at if existing is not None else now


def _checkpoint(index: DiscoveryIndex, relay: str, seq: int, now: datetime) -> None:
    """Persist the cursor and commit a firehose checkpoint at ``seq``."""
    index.put_cursor(SyncCursor(relay=relay, seq=seq, updated_at=now))
    index.commit(f"firehose refresh to seq {seq}")


def _card_for_firehose(
    event: FirehoseEvent,
    corpus_uri: str,
    existing: DatasetCard | None,
    *,
    endpoint: str,
    now: datetime,
) -> DatasetCard | None:
    """Build the card for a corpus create/update event, or ``None`` if undecodable."""
    corpus = corpus_from_value(event.record)
    if corpus is None:
        return None
    provenance = CardProvenance(
        source_did=event.repo,
        source_endpoint=endpoint,
        discovered_via="firehose",
    )
    freshness = CardFreshness(
        first_seen_at=_first_seen(existing, now),
        last_updated_at=now,
        last_seen_seq=event.seq,
    )
    return card_from_corpus(
        corpus_uri,
        corpus,
        provenance=provenance,
        freshness=freshness,
    )


class _EventOutcome(dx.Model):
    """The result of applying one firehose event to the index.

    Attributes
    ----------
    kind : str
        One of ``"built"``, ``"unchanged"``, ``"removed"``, or ``"skipped"``.
    reason : str or None
        A human-readable skip reason when ``kind`` is ``"skipped"``.
    """

    kind: str = dx.field(description="built, unchanged, removed, or skipped")
    reason: str | None = dx.field(default=None, description="skip reason when skipped")


def _apply_firehose_event(
    index: DiscoveryIndex,
    event: FirehoseEvent,
    *,
    endpoint: str,
    now: datetime,
) -> _EventOutcome:
    """Apply one firehose event to the index and classify its outcome."""
    corpus_uri = f"at://{event.repo}/{event.collection}/{event.rkey}"
    if event.action == "delete":
        if index.remove_card(corpus_uri):
            return _EventOutcome(kind="removed")
        return _EventOutcome(
            kind="skipped",
            reason=f"seq {event.seq}: delete of unindexed corpus",
        )
    if event.action not in {"create", "update"}:
        return _EventOutcome(
            kind="skipped",
            reason=f"seq {event.seq}: {event.action} not indexed",
        )
    existing = index.get_card(corpus_uri)
    card = _card_for_firehose(event, corpus_uri, existing, endpoint=endpoint, now=now)
    if card is None:
        return _EventOutcome(
            kind="skipped",
            reason=f"seq {event.seq}: undecodable corpus",
        )
    if _refresh_card(index, card, existing):
        return _EventOutcome(kind="built")
    return _EventOutcome(kind="unchanged")


def build_index(  # noqa: PLR0913  (crawl inputs plus a logged bound)
    index: DiscoveryIndex,
    dids: Iterable[str],
    *,
    describe: RepoDescriber,
    list_corpora: CorpusLister,
    endpoint: str,
    max_repos: int | None = None,
    message: str = "backfill crawl",
) -> CrawlReport:
    """Crawl repositories on one endpoint and index their corpora.

    For each DID, ``describe_repo`` reveals whether the repo holds the corpus
    collection; if so, its corpora are listed and turned into cards. Per-repo
    crawl state is recorded so a re-run resumes, and a ``max_repos`` bound is
    logged rather than silently applied.

    Parameters
    ----------
    index : lairs.discovery.index.DiscoveryIndex
        The index to write into.
    dids : collections.abc.Iterable of str
        The repository DIDs to crawl (for example ``PdsClient.list_repos()``).
    describe : RepoDescriber
        A repository-description source bound to ``endpoint``.
    list_corpora : CorpusLister
        A record-listing source bound to ``endpoint``.
    endpoint : str
        The PDS or relay endpoint the repos are read from.
    max_repos : int or None, optional
        A bound on repositories visited; hitting it is logged.
    message : str, optional
        The commit message for the crawl snapshot.

    Returns
    -------
    CrawlReport
        Counts and skip reasons for the crawl.
    """
    now = datetime.now(UTC)
    seen = with_corpora = built = unchanged = 0
    skipped: list[str] = []
    for did in dids:
        if max_repos is not None and seen >= max_repos:
            skipped.append(f"bound reached at {max_repos} repos (--max-repos)")
            break
        seen += 1
        try:
            description = describe.describe_repo(did)
        except httpx.HTTPError as exc:
            skipped.append(f"{did}: describe_repo failed ({exc})")
            continue
        if _CORPUS_NSID not in description.collections:
            index.put_crawl_state(
                RepoCrawlState(did=did, endpoint=endpoint, last_crawled_at=now),
            )
            skipped.append(f"{did}: no {_CORPUS_NSID}")
            continue
        with_corpora += 1
        found = 0
        handle = description.handle or None
        for envelope in list_corpora.list_records(did, _CORPUS_NSID):
            corpus = corpus_from_value(envelope.value)
            if corpus is None:
                skipped.append(f"{envelope.uri}: undecodable corpus")
                continue
            found += 1
            existing = index.get_card(envelope.uri)
            provenance = CardProvenance(
                source_did=did,
                source_endpoint=endpoint,
                discovered_via="crawl",
                source_handle=handle,
            )
            freshness = CardFreshness(
                first_seen_at=_first_seen(existing, now),
                last_updated_at=now,
            )
            card = card_from_corpus(
                envelope.uri,
                corpus,
                provenance=provenance,
                freshness=freshness,
            )
            if _refresh_card(index, card, existing):
                built += 1
            else:
                unchanged += 1
        index.put_crawl_state(
            RepoCrawlState(
                did=did,
                endpoint=endpoint,
                has_layers_corpus=True,
                corpora_found=found,
                last_crawled_at=now,
            ),
        )
    revision = index.commit(message) if seen else None
    return CrawlReport(
        repos_seen=seen,
        repos_with_corpora=with_corpora,
        cards_built=built,
        cards_unchanged=unchanged,
        skipped=tuple(skipped),
        revision=revision,
    )


def update_index(
    index: DiscoveryIndex,
    relay: str,
    *,
    source_endpoint: str | None = None,
    limit: int | None = None,
    commit_every: int = _DEFAULT_COMMIT_EVERY,
) -> CrawlReport:
    """Tail a relay's firehose, refreshing cards for corpus commits.

    Resumes from the stored ``SyncCursor`` for the relay, indexes each corpus
    create or update, removes the card for each corpus delete (so the local index
    does not drift stale), and checkpoints the cursor and commits every
    ``commit_every`` events. ``limit`` bounds the events processed, which makes
    a live tail testable. A delete of a corpus that is not indexed is logged in
    ``skipped`` rather than removed; a removed card is reported in
    ``CrawlReport.cards_removed``.

    Parameters
    ----------
    index : lairs.discovery.index.DiscoveryIndex
        The index to write into.
    relay : str
        The firehose endpoint.
    source_endpoint : str or None, optional
        The endpoint recorded as each card's provenance; defaults to ``relay``.
    limit : int or None, optional
        A bound on events processed; ``None`` tails indefinitely.
    commit_every : int, optional
        How many events to process between cursor checkpoints.

    Returns
    -------
    CrawlReport
        Counts and skip reasons for the firehose pass.
    """
    endpoint = source_endpoint if source_endpoint is not None else relay
    cursor = index.get_cursor(relay)
    start = cursor.seq if cursor is not None else None
    now = datetime.now(UTC)
    seen = 0
    counts = {"built": 0, "unchanged": 0, "removed": 0}
    last_seq = start if start is not None else 0
    skipped: list[str] = []
    for event in subscribe_repos(relay, nsids=[_CORPUS_NSID], cursor=start):
        if limit is not None and seen >= limit:
            break
        seen += 1
        last_seq = event.seq
        outcome = _apply_firehose_event(index, event, endpoint=endpoint, now=now)
        if outcome.kind == "skipped":
            if outcome.reason is not None:
                skipped.append(outcome.reason)
        else:
            counts[outcome.kind] += 1
        if seen % commit_every == 0:
            _checkpoint(index, relay, last_seq, now)
    revision: str | None = None
    if seen:
        # commit a final checkpoint unless the last event already landed exactly
        # on a ``commit_every`` boundary, which would leave nothing newly staged.
        if seen % commit_every != 0:
            _checkpoint(index, relay, last_seq, now)
        revision = index.head()
    return CrawlReport(
        cards_built=counts["built"],
        cards_unchanged=counts["unchanged"],
        cards_removed=counts["removed"],
        skipped=tuple(skipped),
        revision=revision,
    )
