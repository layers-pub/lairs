"""Firehose consumer.

Consumes ``com.atproto.sync.subscribeRepos`` over a websocket and yields the
commit events whose collection matches the Layers NSIDs, to keep a local store
fresh. Each frame is a pair of DAG-CBOR values (a header and a body); commit
bodies carry an embedded CAR archive whose blocks hold the created and updated
record values, which are recovered through the shared CAR primitives and
rendered to the same DAG-JSON shape the XRPC record endpoints emit.

By default ``subscribe_repos`` is a single-connection primitive: a closed
websocket ends iteration cleanly and the caller resumes from the highest event
``seq`` it saw. Passing ``reconnect=True`` makes it re-dial on a dropped
connection, resuming from the highest delivered ``seq`` so the freshness loop
survives a transient blip.

The websocket transport is provided by the ``websockets`` library, a core
runtime dependency. Integration-marked tests exercise the consumer against a
live PDS firehose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import didactic.api as dx
import libipld
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from lairs._types import JsonValue  # noqa: TC001  (runtime: didactic field sort)
from lairs.atproto._car import ipld_to_json

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from lairs.atproto._car import IpldValue

__all__ = ["FirehoseEvent", "RepoSubscriber", "subscribe_repos"]

_SUBSCRIBE_REPOS_NSID = "com.atproto.sync.subscribeRepos"
"""The XRPC subscription method for the repo firehose."""

LAYERS_NSID_PREFIX = "pub.layers."
"""The NSID prefix used to filter the firehose to Layers collections."""

_FRAME_PARTS = 2
"""The number of concatenated DAG-CBOR values in a firehose frame."""

_MESSAGE_OP = 1
"""The header ``op`` value for a normal (non-error) firehose message."""

_COMMIT_TYPE = "#commit"
"""The header ``t`` value identifying a repository commit message."""


class FirehoseEvent(dx.Model):
    """A single decoded commit event from the repo firehose.

    Attributes
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


def _subscription_url(relay: str, cursor: int | None) -> str:
    """Build the ``subscribeRepos`` websocket URL for a relay or PDS.

    Parameters
    ----------
    relay : str
        The relay or PDS firehose endpoint, with or without the XRPC path.
    cursor : int or None
        A sequence number to resume from, appended as a query parameter.

    Returns
    -------
    str
        The fully qualified subscription URL.
    """
    base = relay.rstrip("/")
    if f"/xrpc/{_SUBSCRIBE_REPOS_NSID}" not in base:
        base = f"{base}/xrpc/{_SUBSCRIBE_REPOS_NSID}"
    if cursor is not None:
        return f"{base}?cursor={cursor}"
    return base


def _keep_predicate(nsids: Sequence[str] | None) -> Callable[[str], bool]:
    """Build a collection filter from an nsid set or the Layers default.

    Parameters
    ----------
    nsids : collections.abc.Sequence of str or None
        The collection NSIDs to keep; ``None`` keeps every collection under
        the Layers prefix.

    Returns
    -------
    collections.abc.Callable
        A predicate that returns whether a collection NSID is kept.
    """
    if nsids is None:
        return lambda collection: collection.startswith(LAYERS_NSID_PREFIX)
    allowed = frozenset(nsids)
    return lambda collection: collection in allowed


def _commit_store(blocks: IpldValue) -> Mapping[bytes, IpldValue]:
    """Decode a commit's embedded CAR archive into a block store.

    Parameters
    ----------
    blocks : IpldValue
        The commit's ``blocks`` field, a CAR archive as raw bytes.

    Returns
    -------
    collections.abc.Mapping of bytes to IpldValue
        The block store keyed by raw CID bytes, empty when no blocks are
        present (for example on a ``tooBig`` commit).
    """
    if not isinstance(blocks, bytes) or not blocks:
        return {}
    _header, store = libipld.decode_car(blocks)
    return store if isinstance(store, dict) else {}


def _op_event(
    op: IpldValue,
    seq: int,
    repo: str,
    store: Mapping[bytes, IpldValue],
    keep: Callable[[str], bool],
) -> FirehoseEvent | None:
    """Build a firehose event from one commit op, or ``None`` if filtered out.

    Parameters
    ----------
    op : IpldValue
        A single commit op with ``path``, ``action``, and optional ``cid``.
    seq : int
        The commit's sequence number.
    repo : str
        The DID of the repository the commit came from.
    store : collections.abc.Mapping of bytes to IpldValue
        The commit's block store, used to resolve created and updated records.
    keep : collections.abc.Callable
        The collection filter predicate.

    Returns
    -------
    FirehoseEvent or None
        The event, or ``None`` if the op is malformed or filtered out.
    """
    if not isinstance(op, dict):
        return None
    path = op.get("path")
    action = op.get("action")
    if not isinstance(path, str) or not isinstance(action, str):
        return None
    collection, _, rkey = path.partition("/")
    if not keep(collection):
        return None
    record: JsonValue = None
    cid = op.get("cid")
    if isinstance(cid, bytes):
        block = store.get(cid)
        if block is not None:
            record = ipld_to_json(block)
    return FirehoseEvent(
        seq=seq,
        repo=repo,
        collection=collection,
        rkey=rkey,
        action=action,
        record=record,
    )


def _commit_events(
    message: bytes,
    keep: Callable[[str], bool],
) -> Iterator[FirehoseEvent]:
    """Decode one firehose frame, yielding the kept commit events.

    Non-commit frames (identity, account, error) and ops whose collection is
    not kept are skipped.

    Parameters
    ----------
    message : bytes
        One binary websocket frame: a header and a body, concatenated as two
        DAG-CBOR values.
    keep : collections.abc.Callable
        The collection filter predicate.

    Yields
    ------
    FirehoseEvent
        The kept commit events from the frame.
    """
    parts = libipld.decode_dag_cbor_multi(message)
    if len(parts) < _FRAME_PARTS:
        return
    header = parts[0]
    body = parts[1]
    if not isinstance(header, dict):
        return
    if header.get("op") != _MESSAGE_OP or header.get("t") != _COMMIT_TYPE:
        return
    if not isinstance(body, dict):
        return
    seq = body.get("seq")
    repo = body.get("repo")
    ops = body.get("ops")
    if (
        not isinstance(seq, int)
        or not isinstance(repo, str)
        or not isinstance(ops, list)
    ):
        return
    store = _commit_store(body.get("blocks"))
    for op in ops:
        event = _op_event(op, seq, repo, store, keep)
        if event is not None:
            yield event


def _stream_one_connection(
    url: str,
    keep: Callable[[str], bool],
    on_seq: Callable[[int], None],
) -> Iterator[FirehoseEvent]:
    """Stream events from a single websocket connection until it closes.

    Parameters
    ----------
    url : str
        The fully qualified subscription URL.
    keep : collections.abc.Callable
        The collection filter predicate.
    on_seq : collections.abc.Callable
        A callback invoked with each yielded event's sequence number so the
        caller can track the highest seen seq for resumption.

    Yields
    ------
    FirehoseEvent
        Decoded commit events for the kept collections, until the websocket
        is closed by either peer.
    """
    # max_size is disabled because commit frames can exceed the default cap.
    with connect(url, max_size=None) as websocket:
        while True:
            try:
                message = websocket.recv()
            except ConnectionClosed:
                return
            if isinstance(message, bytes):
                for event in _commit_events(message, keep):
                    on_seq(event.seq)
                    yield event


def subscribe_repos(
    relay: str,
    *,
    nsids: Sequence[str] | None = None,
    cursor: int | None = None,
    reconnect: bool = False,
) -> Iterator[FirehoseEvent]:
    """Subscribe to the repo firehose, filtered to the Layers NSIDs.

    Opens a websocket to ``com.atproto.sync.subscribeRepos`` and yields one
    event per kept commit op as frames arrive. The stream is live and unbounded;
    the consumer controls how many events to take and closing the generator
    closes the websocket.

    By default this is a single-connection primitive: when the websocket closes
    (a deliberate close or a transient network drop) iteration ends cleanly and
    the caller owns reconnect and cursor bookkeeping. Each ``FirehoseEvent``
    carries its ``seq``, so a caller tracking the highest seen ``seq`` can
    resume by passing it as ``cursor`` on a fresh call. Pass ``reconnect=True``
    to have this function re-dial automatically on a dropped connection,
    resuming from the highest ``seq`` it has already delivered so the freshness
    loop survives a blip.

    Parameters
    ----------
    relay : str
        The relay or PDS firehose endpoint, with or without the XRPC path (for
        example ``wss://bsky.network`` or ``ws://localhost:3000``).
    nsids : collections.abc.Sequence of str or None, optional
        The collection NSIDs to keep; defaults to every collection under
        ``pub.layers.``.
    cursor : int or None, optional
        A sequence number to resume from.
    reconnect : bool, optional
        When ``True``, re-dial on a dropped connection, resuming from the
        highest ``seq`` already delivered (or the original ``cursor`` when no
        event has been delivered yet). When ``False`` (the default), a closed
        connection ends iteration and the caller owns resumption.

    Yields
    ------
    FirehoseEvent
        Decoded commit events for the kept collections.
    """
    keep = _keep_predicate(nsids)
    last_seq = cursor
    seen: dict[str, int | None] = {"seq": last_seq}

    def _track(seq: int) -> None:
        seen["seq"] = seq

    if not reconnect:
        url = _subscription_url(relay, last_seq)
        yield from _stream_one_connection(url, keep, _track)
        return
    while True:
        url = _subscription_url(relay, seen["seq"])
        yield from _stream_one_connection(url, keep, _track)
