"""Single-actor collection discovery: list an actor's catalogue collections.

Resolves a handle or DID and lists the actor's ``pub.layers.catalog.collection``
records as ``CollectionSummary`` rows, preferring an appview when one is available
(server-side facets through ``catalog.listCollections``) and falling back to
direct PDS enumeration. This is the catalogue-collection parallel to
:func:`lairs.discovery.actor.list_datasets`, added additively so the corpus
listing path is untouched; it reuses that module's identity-resolution and client
seams.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.discovery.actor import (
    _actor_did,
    _appview_for,
    _pds_for,
    _resolve_for_pds,
    _use_appview,
)
from lairs.discovery.collection_summary import (
    listcollections_params,
    matches,
    summary_from_envelope,
)

if TYPE_CHECKING:
    from lairs.atproto.appview import AppviewClient
    from lairs.atproto.identity import IdentityResolver
    from lairs.atproto.pds import PdsClient
    from lairs.discovery.models import CollectionFilter, CollectionSummary

__all__ = ["list_collections"]

_CATALOG_COLLECTION_NSID = "pub.layers.catalog.collection"
"""The collection NSID of a catalogue collection record."""

_SOURCE_PDS = "pds"
_SOURCE_APPVIEW = "appview"
_SOURCE_AUTO = "auto"
_VALID_SOURCES = frozenset({_SOURCE_PDS, _SOURCE_APPVIEW, _SOURCE_AUTO})
"""The accepted ``source`` values, mirroring ``list_datasets``."""


def list_collections(  # noqa: PLR0913  (optional source knobs plus test-injection seams)
    actor: str,
    *,
    source: str = "auto",
    appview: str | None = None,
    filters: CollectionFilter | None = None,
    resolver: IdentityResolver | None = None,
    pds_client: PdsClient | None = None,
    appview_client: AppviewClient | None = None,
) -> tuple[CollectionSummary, ...]:
    """List an actor's catalogue collections as summaries.

    Resolves ``actor`` (handle or DID), lists its collections through an appview
    when available (server-side scalar facets on ``catalog.listCollections``) or
    direct PDS enumeration otherwise, maps each to a ``CollectionSummary``, and
    applies the remaining facets client-side.

    Parameters
    ----------
    actor : str
        A handle or DID to list collections for.
    source : str, optional
        One of ``"auto"``, ``"pds"``, or ``"appview"``.
    appview : str or None, optional
        An appview base URL; enables the appview path under ``auto``.
    filters : CollectionFilter or None, optional
        Facet and text filters.
    resolver : IdentityResolver or None, optional
        An injected identity resolver.
    pds_client : PdsClient or None, optional
        An injected PDS client.
    appview_client : AppviewClient or None, optional
        An injected appview client.

    Returns
    -------
    tuple of CollectionSummary
        The matching collection summaries, in source order.

    Raises
    ------
    ValueError
        If ``source`` is unknown, or a required endpoint or client is missing.
    """
    if source not in _VALID_SOURCES:
        msg = f"unknown source: {source!r}"
        raise ValueError(msg)
    summaries: list[CollectionSummary] = []
    if _use_appview(source, appview, appview_client):
        did, handle = _actor_did(actor, resolver=resolver)
        client, owns = _appview_for(appview, appview_client)
        try:
            envelopes = list(
                client.list(
                    "catalog.listCollections",
                    listcollections_params(did, filters),
                ),
            )
        finally:
            if owns:
                client.close()
        endpoint = appview
    else:
        did, endpoint, handle = _resolve_for_pds(
            actor,
            resolver=resolver,
            pds_client=pds_client,
        )
        pds, owns_pds = _pds_for(endpoint, pds_client)
        try:
            envelopes = list(pds.list_records(did, _CATALOG_COLLECTION_NSID))
        finally:
            if owns_pds:
                pds.close()
    for envelope in envelopes:
        summary = summary_from_envelope(
            envelope,
            did=did,
            handle=handle,
            source_endpoint=endpoint,
        )
        if summary is not None:
            summaries.append(summary)
    return tuple(summary for summary in summaries if matches(summary, filters))
