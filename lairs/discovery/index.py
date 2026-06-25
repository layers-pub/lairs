"""The discovery index: dataset cards over a panproto Repository.

``DiscoveryIndex`` is a thin behavioral wrapper around the panproto-backed
``lairs.store.repository.Repository``. The Repository is the source of truth: it
stores ``DatasetCard``, ``SyncCursor``, and ``RepoCrawlState`` records under the
local ``lairs.index.*`` namespace, versioned and content-addressed. Re-saving an
unchanged card is a no-op at commit time, so dedup and idempotent re-crawl are
free, and ``repo.diff`` answers "what datasets changed between two snapshots".
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Self

import didactic.api as dx

from lairs._aturi import nsid_of
from lairs.discovery.cards import (
    CARD_NSID,
    CRAWL_STATE_NSID,
    CURSOR_NSID,
    INDEX_DID,
    DatasetCard,
    RepoCrawlState,
    SyncCursor,
    card_uri,
)
from lairs.store.pool import ModelPool
from lairs.store.repository import Repository, Workspace

if TYPE_CHECKING:
    from pathlib import Path

    from lairs._types import JsonValue

__all__ = ["CardDiff", "DiscoveryIndex"]

_RKEY_LENGTH = 24
"""The hex digest length used for synthetic index record keys."""


class CardDiff(dx.Model):
    """Dataset cards added, removed, or changed between two index revisions.

    The members are corpus AT-URIs when the card is resolvable in the current
    index, falling back to the card's own index URI otherwise (for example a
    removed card).

    Attributes
    ----------
    added : tuple of str
        Corpora whose card appeared between the revisions.
    removed : tuple of str
        Corpora whose card disappeared between the revisions.
    changed : tuple of str
        Corpora whose card content changed between the revisions.
    """

    added: tuple[str, ...] = dx.field(default_factory=tuple, description="added")
    removed: tuple[str, ...] = dx.field(default_factory=tuple, description="removed")
    changed: tuple[str, ...] = dx.field(default_factory=tuple, description="changed")


def _digest_uri(nsid: str, key: str) -> str:
    """Build a deterministic index AT-URI for a keyed bookkeeping record."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:_RKEY_LENGTH]
    return f"at://{INDEX_DID}/{nsid}/{digest}"


class DiscoveryIndex:
    """A panproto-backed store of dataset cards and crawl bookkeeping.

    Parameters
    ----------
    repo : lairs.store.repository.Repository
        The backing Repository that holds the index records.
    """

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    @classmethod
    def init(cls, path: Path) -> Self:
        """Create a new index Repository at ``path``.

        Parameters
        ----------
        path : pathlib.Path
            The directory to create the index Repository in.

        Returns
        -------
        DiscoveryIndex
            The new index.
        """
        return cls(Repository.init(path))

    @classmethod
    def open(cls, path: Path) -> Self:
        """Open an existing index Repository at ``path``.

        Parameters
        ----------
        path : pathlib.Path
            The directory of an existing index Repository.

        Returns
        -------
        DiscoveryIndex
            The opened index.
        """
        return cls(Repository.open(path))

    @property
    def repo(self) -> Repository:
        """Return the backing Repository.

        Returns
        -------
        lairs.store.repository.Repository
            The Repository that holds the index records.
        """
        return self._repo

    def put_card(self, card: DatasetCard) -> str:
        """Stage a dataset card, keyed by its deterministic index URI.

        Parameters
        ----------
        card : lairs.discovery.cards.DatasetCard
            The card to store.

        Returns
        -------
        str
            The card's index AT-URI.
        """
        uri = card_uri(card.summary.uri)
        self._repo.save(uri, card)
        return uri

    def get_card(self, corpus_uri: str) -> DatasetCard | None:
        """Load the card for a corpus, or ``None`` when it is not indexed.

        Parameters
        ----------
        corpus_uri : str
            The corpus AT-URI.

        Returns
        -------
        DatasetCard or None
            The stored card, or ``None``.
        """
        loaded = self._repo.load(card_uri(corpus_uri), DatasetCard)
        return loaded if isinstance(loaded, DatasetCard) else None

    def remove_card(self, corpus_uri: str) -> bool:
        """Remove a corpus's card from the index, returning whether one existed.

        Stages the card's removal through the backing Repository so the card is
        absent from :meth:`cards`, :meth:`get_card`, and search, and a
        revision-to-revision :meth:`diff_cards` reports it in ``removed`` once the
        removal is committed. Removing a card that is not indexed is a no-op.

        Parameters
        ----------
        corpus_uri : str
            The corpus AT-URI whose card to remove.

        Returns
        -------
        bool
            ``True`` if a card was removed, ``False`` if none was indexed.
        """
        uri = card_uri(corpus_uri)
        try:
            self._repo.forget(uri)
        except KeyError:
            return False
        return True

    def cards(self) -> list[DatasetCard]:
        """Load every dataset card in the index.

        Returns
        -------
        list of DatasetCard
            All stored cards, in index key order.
        """
        workspace = Workspace(self._repo)
        cards: list[DatasetCard] = []
        for uri in workspace.uris_of(CARD_NSID):
            loaded = self._repo.load(uri, DatasetCard)
            if isinstance(loaded, DatasetCard):
                cards.append(loaded)
        return cards

    def card_pool(self) -> ModelPool:
        """Load every card into a ``ModelPool`` keyed by its index URI.

        Returns
        -------
        lairs.store.pool.ModelPool
            A pool of the index's cards, for cross-reference traversal.
        """
        pool = ModelPool()
        for card in self.cards():
            pool.add(card_uri(card.summary.uri), card)
        return pool

    def get_cursor(self, relay: str) -> SyncCursor | None:
        """Load the firehose cursor for a relay, or ``None``.

        Parameters
        ----------
        relay : str
            The firehose endpoint.

        Returns
        -------
        SyncCursor or None
            The stored cursor, or ``None``.
        """
        loaded = self._repo.load(_digest_uri(CURSOR_NSID, relay), SyncCursor)
        return loaded if isinstance(loaded, SyncCursor) else None

    def put_cursor(self, cursor: SyncCursor) -> None:
        """Stage a firehose cursor.

        Parameters
        ----------
        cursor : lairs.discovery.cards.SyncCursor
            The cursor to store.
        """
        self._repo.save(_digest_uri(CURSOR_NSID, cursor.relay), cursor)

    def get_crawl_state(self, did: str) -> RepoCrawlState | None:
        """Load the crawl state for a repository, or ``None``.

        Parameters
        ----------
        did : str
            The repository DID.

        Returns
        -------
        RepoCrawlState or None
            The stored crawl state, or ``None``.
        """
        loaded = self._repo.load(_digest_uri(CRAWL_STATE_NSID, did), RepoCrawlState)
        return loaded if isinstance(loaded, RepoCrawlState) else None

    def put_crawl_state(self, state: RepoCrawlState) -> None:
        """Stage a repository crawl state.

        Parameters
        ----------
        state : lairs.discovery.cards.RepoCrawlState
            The crawl state to store.
        """
        self._repo.save(_digest_uri(CRAWL_STATE_NSID, state.did), state)

    def commit(self, message: str) -> str:
        """Commit the staged index records.

        Parameters
        ----------
        message : str
            The commit message.

        Returns
        -------
        str
            The new commit revision.
        """
        return self._repo.commit(message)

    def tag(self, name: str, *, revision: str | None = None) -> None:
        """Tag an index revision (the head by default).

        Parameters
        ----------
        name : str
            The tag name.
        revision : str or None, optional
            The revision to tag; defaults to the head.
        """
        self._repo.tag(name, revision=revision)

    def head(self) -> str | None:
        """Return the head commit revision, or ``None`` when empty.

        Returns
        -------
        str or None
            The head revision.
        """
        return self._repo.head()

    def log(self) -> list[dict[str, JsonValue]]:
        """Return the commit log, newest first.

        Returns
        -------
        list of dict
            The commit log entries.
        """
        return self._repo.log()

    def diff_cards(self, base: str, head: str) -> CardDiff:
        """Diff dataset cards between two index revisions.

        Parameters
        ----------
        base : str
            The base revision.
        head : str
            The head revision.

        Returns
        -------
        CardDiff
            The added, removed, and changed corpora between the revisions.
        """
        record_diff = self._repo.diff(base, head)
        current = {
            card_uri(card.summary.uri): card.summary.uri for card in self.cards()
        }

        def to_corpora(uris: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(
                current.get(uri, uri) for uri in uris if nsid_of(uri) == CARD_NSID
            )

        return CardDiff(
            added=to_corpora(record_diff.added),
            removed=to_corpora(record_diff.removed),
            changed=to_corpora(record_diff.changed),
        )
