"""Shared PDS graph loader for the data surfaces.

A generic, model-map-parameterized loader that enumerates an authority's Layers
collections and follows AT-URI references across account boundaries, building a
:class:`~lairs.store.pool.ModelPool` keyed by AT-URI. A Layers dataset fans out
across many accounts (its collection, corpora, sessions, media, participants, and
so on each in a separate repository), so the loader follows every AT-URI
reference a loaded record carries, transitively and across account boundaries, to
pull in the component records the entry cites.

The :class:`~lairs.data.corpus.Corpus` surface predates this module and keeps its
own copy of these helpers; the collection and acquisition surfaces share this one
so the ref-following graph walk lives in one place. Each surface supplies its own
NSID-to-model map, so the walk only decodes and follows the record types that
surface cares about.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import didactic.api as dx
import httpx

from lairs._aturi import authority_of, nsid_of, rkey_of
from lairs.atproto.pds import RecordNotFoundError, decode
from lairs.store.pool import ModelPool

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from lairs._types import JsonValue
    from lairs.atproto.pds import RecordEnvelope

__all__ = [
    "PdsSource",
    "collect_at_uris",
    "decode_envelope",
    "load_graph",
    "refs_of",
]

# the minimum number of AT-URI path segments needed to carry a record key.
_MIN_PARTS_WITH_RKEY = 3


@runtime_checkable
class PdsSource(Protocol):
    """The read-only PDS surface the graph loader consumes.

    Satisfied structurally by :class:`lairs.atproto.pds.PdsClient` and by test
    fakes, so a loader can be exercised without network access.
    """

    def list_records(
        self,
        repo: str,
        collection: str,
    ) -> Iterator[RecordEnvelope]:
        """Enumerate a repository's records in a collection."""
        ...

    def get_record(
        self,
        repo: str,
        collection: str,
        rkey: str,
    ) -> RecordEnvelope:
        """Fetch a single record by repo, collection, and rkey."""
        ...


def decode_envelope(
    envelope: RecordEnvelope,
    nsid_models: Mapping[str, type[dx.Model]],
) -> tuple[str, dx.Model] | None:
    """Decode a record envelope into an AT-URI and model, by its collection.

    Returns ``None`` when the collection is not one of ``nsid_models``, the value
    is not a decodable object, or the value fails validation, so a single
    undecodable record is skipped rather than aborting a whole-graph load. The
    wire-only ``$type`` discriminator is dropped and blob refs are normalized by
    :func:`lairs.atproto.pds.decode`.

    Parameters
    ----------
    envelope : lairs.atproto.pds.RecordEnvelope
        The record envelope to decode.
    nsid_models : collections.abc.Mapping of str to type
        The collection-NSID-to-model map the loader decodes against.

    Returns
    -------
    tuple of (str, didactic.api.Model) or None
        The AT-URI and decoded model, or ``None`` when it is not decodable.
    """
    model_cls = nsid_models.get(nsid_of(envelope.uri))
    if model_cls is None:
        return None
    try:
        model = decode(envelope, model_cls)
    except dx.ValidationError, TypeError, ValueError:
        return None
    return envelope.uri, model


def collect_at_uris(value: JsonValue, refs: set[str]) -> None:
    """Collect every ``at://`` string reachable in a JSON value into ``refs``.

    Parameters
    ----------
    value : JsonValue
        The JSON value to walk.
    refs : set of str
        The accumulator the discovered AT-URIs are added to.
    """
    if isinstance(value, str):
        if value.startswith("at://"):
            refs.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            collect_at_uris(item, refs)
    elif isinstance(value, list):
        for item in value:
            collect_at_uris(item, refs)


def refs_of(model: dx.Model) -> set[str]:
    """Return the AT-URIs a record references.

    Every ``at://`` string anywhere in the record value is a reference to another
    record, possibly in a different account. The value is dumped to JSON and
    walked, so nested objects, lists, and embedded models are all covered.

    Parameters
    ----------
    model : didactic.api.Model
        The decoded record to scan.

    Returns
    -------
    set of str
        The referenced AT-URIs.
    """
    refs: set[str] = set()
    collect_at_uris(json.loads(model.model_dump_json()), refs)
    return refs


def _fetch_ref(
    uri: str,
    client: PdsSource,
    nsid_models: Mapping[str, type[dx.Model]],
) -> tuple[str, dx.Model] | None:
    """Fetch and decode a single referenced record by AT-URI.

    The record is fetched from the authority embedded in the AT-URI, which the
    PDS resolves whether it is a handle or a DID, so a reference into another
    account is followed without separate identity resolution. A reference that
    does not resolve or fails to decode is skipped.

    Parameters
    ----------
    uri : str
        The referenced record's AT-URI.
    client : PdsSource
        The PDS source to read through.
    nsid_models : collections.abc.Mapping of str to type
        The collection-NSID-to-model map the loader decodes against.

    Returns
    -------
    tuple of (str, didactic.api.Model) or None
        The AT-URI and decoded model, or ``None`` when it cannot be fetched or
        decoded.
    """
    authority = authority_of(uri)
    collection = nsid_of(uri)
    rkey = rkey_of(uri)
    if not authority or not collection or not rkey:
        return None
    try:
        envelope = client.get_record(authority, collection, rkey)
    except httpx.HTTPError, RecordNotFoundError:
        return None
    return decode_envelope(envelope, nsid_models)


def load_graph(
    uri: str,
    nsid_models: Mapping[str, type[dx.Model]],
    client: PdsSource,
    *,
    follow_refs: bool = True,
) -> ModelPool:
    """Load a record graph from a PDS, optionally following refs across accounts.

    The AT-URI's authority is enumerated first, reading every collection in
    ``nsid_models`` it hosts. When ``follow_refs`` is true, every AT-URI a loaded
    record references is then fetched, transitively and across account
    boundaries, so the component records that make up the entry are pulled into
    the pool even though they live in separate accounts. References are fetched by
    exact AT-URI, so only the records this entry actually cites are loaded, not
    whole shared accounts.

    Parameters
    ----------
    uri : str
        The entry AT-URI whose authority is enumerated.
    nsid_models : collections.abc.Mapping of str to type
        The collection-NSID-to-model map the loader decodes and follows.
    client : PdsSource
        The PDS source to read through.
    follow_refs : bool, optional
        Whether to follow AT-URI references into other accounts. When false, only
        the entry's own authority is read.

    Returns
    -------
    lairs.store.pool.ModelPool
        The loaded record graph, keyed by AT-URI.
    """
    authority = authority_of(uri)
    pool = ModelPool()
    seen: set[str] = set()
    pending: list[str] = []
    for nsid in nsid_models:
        for envelope in client.list_records(authority, nsid):
            decoded = decode_envelope(envelope, nsid_models)
            if decoded is None:
                continue
            record_uri, model = decoded
            seen.add(record_uri)
            pool.add(record_uri, model)
            if follow_refs:
                pending.extend(refs_of(model))
    while pending:
        ref = pending.pop()
        if ref in seen or nsid_of(ref) not in nsid_models:
            seen.add(ref)
            continue
        seen.add(ref)
        decoded = _fetch_ref(ref, client, nsid_models)
        if decoded is None:
            continue
        record_uri, model = decoded
        seen.add(record_uri)
        pool.add(record_uri, model)
        pending.extend(refs_of(model))
    return pool
