"""Single-actor discovery: list an actor's datasets and repo table of contents.

Resolves a handle or DID through ``IdentityResolver`` and lists the actor's
corpora as ``DatasetSummary`` rows, preferring an appview when one is available
and falling back to direct PDS enumeration. ``table_of_contents`` reads a repo's
collection inventory through ``describe_repo`` without dumping records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.atproto.appview import AppviewClient
from lairs.atproto.identity import IdentityResolver
from lairs.atproto.pds import PdsClient
from lairs.discovery.models import CollectionCount, RepoTableOfContents
from lairs.discovery.summary import (
    _CORPUS_NSID,
    _DATASET_LIKE_NSIDS,
    listcorpora_params,
    matches,
    summary_from_envelope,
)

if TYPE_CHECKING:
    from lairs.discovery.models import DatasetFilter, DatasetSummary

__all__ = ["list_datasets", "table_of_contents"]

_SOURCE_PDS = "pds"
_SOURCE_APPVIEW = "appview"
_SOURCE_AUTO = "auto"
_VALID_SOURCES = frozenset({_SOURCE_PDS, _SOURCE_APPVIEW, _SOURCE_AUTO})
"""The accepted ``source`` values, mirroring ``load_corpus``."""


def _actor_did(
    actor: str,
    *,
    resolver: IdentityResolver | None,
) -> tuple[str, str | None]:
    """Resolve an actor to a ``(did, handle)`` pair without needing its PDS.

    A bare DID is returned as-is (no network), which the appview path uses since
    it does not need the actor's PDS endpoint. A handle is resolved.

    Parameters
    ----------
    actor : str
        A handle or a DID.
    resolver : IdentityResolver or None
        An injected resolver; a throwaway is created and closed when omitted.

    Returns
    -------
    tuple
        The DID and handle (``None`` for a bare DID).
    """
    if actor.startswith("did:"):
        return actor, None
    if resolver is not None:
        resolution = resolver.resolve(actor)
        return resolution.did, resolution.handle
    with IdentityResolver() as active:
        resolution = active.resolve(actor)
    return resolution.did, resolution.handle


def _resolve_for_pds(
    actor: str,
    *,
    resolver: IdentityResolver | None,
    pds_client: PdsClient | None,
) -> tuple[str, str | None, str | None]:
    """Resolve an actor to a ``(did, pds_endpoint, handle)`` triple for PDS reads.

    When ``actor`` is already a DID and a PDS client is injected, resolution is
    skipped so unit tests stay network-free; the endpoint is then unknown but
    unneeded because the injected client carries it.

    Parameters
    ----------
    actor : str
        A handle or a DID.
    resolver : IdentityResolver or None
        An injected resolver; a throwaway is created and closed when omitted.
    pds_client : PdsClient or None
        An injected PDS client, used to detect the network-free DID path.

    Returns
    -------
    tuple
        The resolved DID, PDS endpoint (or ``None``), and handle (or ``None``).
    """
    if actor.startswith("did:") and pds_client is not None:
        return actor, None, None
    if resolver is not None:
        resolution = resolver.resolve(actor)
        return resolution.did, resolution.pds_endpoint, resolution.handle
    with IdentityResolver() as active:
        resolution = active.resolve(actor)
    return resolution.did, resolution.pds_endpoint, resolution.handle


def _pds_for(
    endpoint: str | None,
    client: PdsClient | None,
) -> tuple[PdsClient, bool]:
    """Return a PDS client and whether the caller owns (must close) it."""
    if client is not None:
        return client, False
    if endpoint is None:
        msg = "a pds endpoint or client is required for pds discovery"
        raise ValueError(msg)
    return PdsClient(endpoint), True


def _appview_for(
    appview: str | None,
    client: AppviewClient | None,
) -> tuple[AppviewClient, bool]:
    """Return an appview client and whether the caller owns (must close) it."""
    if client is not None:
        return client, False
    if appview is None:
        msg = "an appview endpoint or client is required for appview discovery"
        raise ValueError(msg)
    return AppviewClient(appview), True


def _use_appview(
    source: str,
    appview: str | None,
    appview_client: AppviewClient | None,
) -> bool:
    """Decide whether to take the appview path for the given source and inputs."""
    if source == _SOURCE_APPVIEW:
        return True
    if source == _SOURCE_PDS:
        return False
    return appview_client is not None or appview is not None


def list_datasets(  # noqa: PLR0913  (optional source knobs plus test-injection seams)
    actor: str,
    *,
    source: str = "auto",
    appview: str | None = None,
    filters: DatasetFilter | None = None,
    resolver: IdentityResolver | None = None,
    pds_client: PdsClient | None = None,
    appview_client: AppviewClient | None = None,
) -> tuple[DatasetSummary, ...]:
    """List an actor's datasets as summaries.

    Resolves ``actor`` (handle or DID), lists its corpora through an appview when
    available (server-side ``language``/``domain`` facets) or direct PDS
    enumeration otherwise, maps each to a ``DatasetSummary``, and applies the
    remaining facets client-side.

    Parameters
    ----------
    actor : str
        A handle or DID to list datasets for.
    source : str, optional
        One of ``"auto"``, ``"pds"``, or ``"appview"``.
    appview : str or None, optional
        An appview base URL; enables the appview path under ``auto``.
    filters : DatasetFilter or None, optional
        Facet and text filters.
    resolver : IdentityResolver or None, optional
        An injected identity resolver.
    pds_client : PdsClient or None, optional
        An injected PDS client.
    appview_client : AppviewClient or None, optional
        An injected appview client.

    Returns
    -------
    tuple of DatasetSummary
        The matching dataset summaries, in source order.

    Raises
    ------
    ValueError
        If ``source`` is unknown, or a required endpoint or client is missing.
    """
    if source not in _VALID_SOURCES:
        msg = f"unknown source: {source!r}"
        raise ValueError(msg)
    summaries: list[DatasetSummary] = []
    if _use_appview(source, appview, appview_client):
        did, handle = _actor_did(actor, resolver=resolver)
        client, owns = _appview_for(appview, appview_client)
        try:
            envelopes = list(
                client.list("corpus.listCorpora", listcorpora_params(did, filters)),
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
            envelopes = list(pds.list_records(did, _CORPUS_NSID))
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


def table_of_contents(
    actor: str,
    *,
    source: str = "auto",
    counts: bool = False,
    resolver: IdentityResolver | None = None,
    pds_client: PdsClient | None = None,
) -> RepoTableOfContents:
    """Read an actor's repository inventory.

    Uses ``describe_repo`` to list the collections present in the repo without
    enumerating records. Counts are filled only when ``counts`` is set, since
    counting drains every collection. This path is always PDS-backed; the
    ``source`` argument is accepted for API symmetry and validated.

    Parameters
    ----------
    actor : str
        A handle or DID.
    source : str, optional
        Accepted for symmetry with ``list_datasets``; the inventory is PDS-backed.
    counts : bool, optional
        Whether to fill per-collection record counts (drains each collection).
    resolver : IdentityResolver or None, optional
        An injected identity resolver.
    pds_client : PdsClient or None, optional
        An injected PDS client.

    Returns
    -------
    RepoTableOfContents
        The repository inventory.

    Raises
    ------
    ValueError
        If ``source`` is unknown, or no PDS endpoint or client is available.
    """
    if source not in _VALID_SOURCES:
        msg = f"unknown source: {source!r}"
        raise ValueError(msg)
    did, pds_endpoint, handle = _resolve_for_pds(
        actor,
        resolver=resolver,
        pds_client=pds_client,
    )
    client, owns = _pds_for(pds_endpoint, pds_client)
    try:
        description = client.describe_repo(did)
        collections: list[CollectionCount] = []
        for nsid in description.collections:
            count = sum(1 for _ in client.list_records(did, nsid)) if counts else None
            collections.append(
                CollectionCount(
                    nsid=nsid,
                    count=count,
                    is_dataset_like=nsid in _DATASET_LIKE_NSIDS,
                ),
            )
        resolved_handle = description.handle or handle
    finally:
        if owns:
            client.close()
    dataset_collections = tuple(
        item.nsid for item in collections if item.is_dataset_like
    )
    return RepoTableOfContents(
        did=did,
        handle=resolved_handle,
        pds_endpoint=pds_endpoint,
        collections=tuple(collections),
        dataset_collections=dataset_collections,
    )
