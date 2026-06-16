"""Optional firehose consumer (deferred to M3).

Consumes ``com.atproto.sync.subscribeRepos`` filtered to the Layers NSIDs to
keep a local store fresh.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from lairs._types import JsonValue

__all__ = ["subscribe_repos"]


def subscribe_repos(
    relay: str,
    *,
    nsids: Sequence[str] | None = None,
    cursor: int | None = None,
) -> Iterator[dict[str, JsonValue]]:
    """Subscribe to the repo firehose filtered to Layers NSIDs.

    Parameters
    ----------
    relay : str
        The relay or PDS firehose endpoint.
    nsids : collections.abc.Sequence of str or None, optional
        The collection NSIDs to keep; defaults to the Layers record set.
    cursor : int or None, optional
        A sequence number to resume from.

    Returns
    -------
    collections.abc.Iterator of dict
        A stream of decoded commit events.

    Raises
    ------
    NotImplementedError
        Always, until live sync lands.
    """
    raise NotImplementedError
