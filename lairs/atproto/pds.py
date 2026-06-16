"""Direct PDS record client.

Wraps ``com.atproto.repo.getRecord`` and ``listRecords`` (with cursor
pagination wrapped into lazy iterators).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lairs._types import JsonValue

__all__ = ["get_record", "list_records"]


def get_record(repo: str, collection: str, rkey: str) -> dict[str, JsonValue]:
    """Fetch a single record by repo, collection, and rkey.

    Parameters
    ----------
    repo : str
        The repository DID or handle.
    collection : str
        The record collection NSID.
    rkey : str
        The record key.

    Returns
    -------
    dict
        The ``{uri, cid, value}`` record envelope.

    Raises
    ------
    NotImplementedError
        Always, until the access layer lands.
    """
    raise NotImplementedError


def list_records(
    repo: str,
    collection: str,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> Iterator[dict[str, JsonValue]]:
    """Enumerate records in a collection with cursor pagination.

    Parameters
    ----------
    repo : str
        The repository DID or handle.
    collection : str
        The record collection NSID.
    limit : int or None, optional
        The page size requested from the PDS.
    cursor : str or None, optional
        An opaque pagination cursor to resume from.

    Returns
    -------
    collections.abc.Iterator of dict
        A lazy iterator over record envelopes across pages.

    Raises
    ------
    NotImplementedError
        Always, until the access layer lands.
    """
    raise NotImplementedError
