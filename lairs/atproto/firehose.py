"""Optional firehose consumer (deferred to M3).

Consumes ``com.atproto.sync.subscribeRepos`` filtered to the Layers NSIDs to
keep a local store fresh. This is deferred to milestone M3: the typed
signatures, the ``RepoSubscriber`` protocol, and the ``FirehoseEvent`` model are
real, but the streaming body raises ``NotImplementedError`` because it depends
on a CAR / DAG-CBOR decoder and a websocket transport that are out of scope for
the read milestone.

Integration-marked tests exercise the deferred surface and skip cleanly until
the consumer lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import didactic.api as dx

from lairs._types import JsonValue  # noqa: TC001  (runtime: didactic field sort)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["FirehoseEvent", "RepoSubscriber", "subscribe_repos"]

_SUBSCRIBE_REPOS_NSID = "com.atproto.sync.subscribeRepos"
"""The XRPC subscription method for the repo firehose."""

LAYERS_NSID_PREFIX = "pub.layers."
"""The NSID prefix used to filter the firehose to Layers collections."""


class FirehoseEvent(dx.Model):
    """A single decoded commit event from the repo firehose.

    Parameters
    ----------
    seq : int
        The monotonically increasing sequence number of the event.
    repo : str
        The DID of the repository the event came from.
    collection : str
        The collection NSID of the affected record.
    rkey : str
        The record key of the affected record.
    action : str
        The commit action (for example ``create``, ``update``, ``delete``).
    record : JsonValue
        The record value for create and update actions, otherwise ``None``.
    """

    seq: int = dx.field(description="monotonic sequence number of the event")
    repo: str = dx.field(description="DID of the repository the event came from")
    collection: str = dx.field(description="collection NSID of the affected record")
    rkey: str = dx.field(description="record key of the affected record")
    action: str = dx.field(description="commit action (create, update, delete)")
    record: JsonValue = dx.field(
        default=None,
        description="record value for create and update actions, otherwise None",
    )


@runtime_checkable
class RepoSubscriber(Protocol):
    """A consumer of the filtered repo firehose.

    Implementations stream ``subscribeRepos`` commit events, decode their CAR
    blocks, and yield the subset whose collection matches the Layers NSIDs.
    """

    def subscribe(
        self,
        *,
        nsids: Sequence[str] | None = None,
        cursor: int | None = None,
    ) -> Iterator[FirehoseEvent]:
        """Stream filtered firehose events.

        Parameters
        ----------
        nsids : collections.abc.Sequence of str or None, optional
            The collection NSIDs to keep; defaults to the Layers record set.
        cursor : int or None, optional
            A sequence number to resume from.

        Yields
        ------
        FirehoseEvent
            Decoded commit events for the kept collections.
        """
        ...


def subscribe_repos(
    relay: str,
    *,
    nsids: Sequence[str] | None = None,
    cursor: int | None = None,
) -> Iterator[FirehoseEvent]:
    """Subscribe to the repo firehose filtered to Layers NSIDs.

    Deferred to M3: this requires a websocket transport and a CAR / DAG-CBOR
    decoder that the read milestone does not ship.

    Parameters
    ----------
    relay : str
        The relay or PDS firehose endpoint.
    nsids : collections.abc.Sequence of str or None, optional
        The collection NSIDs to keep; defaults to collections under
        ``pub.layers.``.
    cursor : int or None, optional
        A sequence number to resume from.

    Yields
    ------
    FirehoseEvent
        Decoded commit events for the kept collections.

    Raises
    ------
    NotImplementedError
        Always, until live sync lands in M3.
    """
    # deferred to m3: see plan section 6.6. the signature and event model are
    # real so downstream live-sync code can be typed against them now.
    _ = (relay, nsids, cursor, _SUBSCRIBE_REPOS_NSID, LAYERS_NSID_PREFIX)
    msg = "firehose live sync is deferred to M3"
    raise NotImplementedError(msg)
    yield  # pragma: no cover - marks this a generator without running
