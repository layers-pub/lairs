"""Federated discovery: fan out over a seed of actors.

Network discovery without a central index: given a seed of handles or DIDs (a
lab roster, a leaderboard, a curated list), list every actor's datasets and merge
them. Per-actor transport and resolution failures are isolated so one
unreachable actor does not abort the sweep.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING

import httpx

from lairs.atproto.identity import IdentityError, IdentityResolver
from lairs.discovery.actor import list_datasets

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.atproto.appview import AppviewClient
    from lairs.atproto.pds import PdsClient
    from lairs.discovery.models import DatasetFilter, DatasetSummary

__all__ = ["datasets_using_ontology", "discover_datasets"]


def discover_datasets(  # noqa: PLR0913  (optional source knobs plus injection seams)
    actors: Sequence[str],
    *,
    source: str = "auto",
    appview: str | None = None,
    filters: DatasetFilter | None = None,
    resolver: IdentityResolver | None = None,
    pds_client: PdsClient | None = None,
    appview_client: AppviewClient | None = None,
) -> tuple[DatasetSummary, ...]:
    """List datasets across a seed of actors, deduplicated by corpus AT-URI.

    Each actor is listed through :func:`lairs.discovery.actor.list_datasets`.
    A single resolver is shared across the whole seed so identity lookups (handle
    to DID, and the DID document that carries the PDS endpoint) are cached and the
    underlying HTTP client is opened once: an injected ``resolver`` is reused as
    is, and when none is given a throwaway resolver is created for the sweep and
    closed before returning. Duplicate corpora (the same AT-URI seen via more than
    one actor or source) collapse to the first occurrence. A per-actor transport
    or resolution failure is skipped, so the sweep is best-effort; a ``ValueError``
    (an unknown source or a missing endpoint) propagates.

    Parameters
    ----------
    actors : collections.abc.Sequence of str
        The seed handles or DIDs to search across.
    source : str, optional
        One of ``"auto"``, ``"pds"``, or ``"appview"``.
    appview : str or None, optional
        An appview base URL; enables the appview path under ``auto``.
    filters : DatasetFilter or None, optional
        Facet and text filters, applied per actor.
    resolver : IdentityResolver or None, optional
        An injected identity resolver, shared across the seed.
    pds_client : PdsClient or None, optional
        An injected PDS client.
    appview_client : AppviewClient or None, optional
        An injected appview client.

    Returns
    -------
    tuple of DatasetSummary
        The merged, deduplicated summaries, in seed-then-corpus order.
    """
    merged: dict[str, DatasetSummary] = {}
    owns_resolver = resolver is None
    shared = IdentityResolver() if owns_resolver else nullcontext(resolver)
    with shared as active:
        for actor in actors:
            try:
                rows = list_datasets(
                    actor,
                    source=source,
                    appview=appview,
                    filters=filters,
                    resolver=active,
                    pds_client=pds_client,
                    appview_client=appview_client,
                )
            except httpx.HTTPError, IdentityError:
                # best-effort fan-out: skip an unreachable or unresolvable actor.
                continue
            for row in rows:
                if row.uri not in merged:
                    merged[row.uri] = row
    return tuple(merged.values())


def datasets_using_ontology(  # noqa: PLR0913  (seed plus optional injection seams)
    ontology_uri: str,
    actors: Sequence[str],
    *,
    source: str = "auto",
    appview: str | None = None,
    resolver: IdentityResolver | None = None,
    pds_client: PdsClient | None = None,
    appview_client: AppviewClient | None = None,
) -> tuple[DatasetSummary, ...]:
    """Find datasets that use a given ontology, across a seed of actors.

    The lexicons offer no ontology-to-corpus query, so this fans out over the
    seed (see :func:`discover_datasets`) and keeps the corpora whose
    ``ontology_refs`` contain ``ontology_uri``. Cross-repo reach is therefore
    bounded by the seed; the Tier 3 index resolves this generally.

    Parameters
    ----------
    ontology_uri : str
        The ontology AT-URI to match against each corpus's ``ontology_refs``.
    actors : collections.abc.Sequence of str
        The seed handles or DIDs to search across.
    source : str, optional
        One of ``"auto"``, ``"pds"``, or ``"appview"``.
    appview : str or None, optional
        An appview base URL.
    resolver : IdentityResolver or None, optional
        An injected identity resolver.
    pds_client : PdsClient or None, optional
        An injected PDS client.
    appview_client : AppviewClient or None, optional
        An injected appview client.

    Returns
    -------
    tuple of DatasetSummary
        The datasets in the seed that reference the ontology.
    """
    found = discover_datasets(
        actors,
        source=source,
        appview=appview,
        resolver=resolver,
        pds_client=pds_client,
        appview_client=appview_client,
    )
    return tuple(summary for summary in found if ontology_uri in summary.ontology_refs)
