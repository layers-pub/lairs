"""Cross-repo, ref-anchored link queries.

These queries are anchored on a content reference (a corpus, an eprint) rather
than a repository, so an appview that indexes the network answers them across
every repo: who, anywhere, asserts membership in this corpus, or links this
eprint to data. They require an appview endpoint or client, since a PDS can only
answer for its own repository.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.atproto.appview import AppviewClient
from lairs.records._generated import catalog as catalog_records
from lairs.records._generated.corpus import Membership
from lairs.records._generated.eprint import DataLink

if TYPE_CHECKING:
    from lairs._types import JsonValue
    from lairs.atproto.pds import QueryParams, RecordEnvelope

__all__ = [
    "Rollup",
    "RollupFacet",
    "RollupFacetValue",
    "RollupWarning",
    "containers_of",
    "datasets_for_eprint",
    "members_of_collection",
    "members_of_corpus",
    "rollup_of_collection",
]


def _appview_for(
    appview: str | None,
    client: AppviewClient | None,
) -> tuple[AppviewClient, bool]:
    """Return an appview client and whether the caller owns (must close) it.

    Parameters
    ----------
    appview : str or None
        An appview base URL.
    client : AppviewClient or None
        An injected appview client.

    Returns
    -------
    tuple
        The client and a flag that is ``True`` when the caller created it.

    Raises
    ------
    ValueError
        If neither an endpoint nor a client is provided.
    """
    if client is not None:
        return client, False
    if appview is None:
        msg = "an appview endpoint or client is required for cross-repo link queries"
        raise ValueError(msg)
    return AppviewClient(appview), True


def _decode_record[T: dx.Model](
    envelope: RecordEnvelope,
    model_cls: type[T],
) -> T | None:
    """Decode an envelope value into a model, or ``None`` on failure.

    Parameters
    ----------
    envelope : lairs.atproto.pds.RecordEnvelope
        The record envelope to decode.
    model_cls : type
        The target model class.

    Returns
    -------
    T or None
        The decoded model, or ``None`` when the value is not a decodable object.
    """
    value = envelope.value
    if not isinstance(value, dict):
        return None
    payload = {key: item for key, item in value.items() if key != "$type"}
    try:
        return model_cls.model_validate_json(json.dumps(payload))
    except dx.ValidationError:
        return None


def members_of_corpus(
    corpus_uri: str,
    *,
    appview: str | None = None,
    appview_client: AppviewClient | None = None,
    split: str | None = None,
) -> tuple[Membership, ...]:
    """List membership records that point at a corpus, across all repos.

    Parameters
    ----------
    corpus_uri : str
        The corpus AT-URI to find members of.
    appview : str or None, optional
        An appview base URL.
    appview_client : AppviewClient or None, optional
        An injected appview client.
    split : str or None, optional
        Restrict to a dataset split (for example ``"train"``).

    Returns
    -------
    tuple of lairs.records._generated.corpus.Membership
        The membership records asserted for the corpus.

    Raises
    ------
    ValueError
        If no appview endpoint or client is available.
    """
    client, owns = _appview_for(appview, appview_client)
    params: QueryParams = {"corpusRef": corpus_uri}
    if split is not None:
        params["split"] = split
    try:
        envelopes = list(client.list("corpus.listMemberships", params))
    finally:
        if owns:
            client.close()
    decoded = [_decode_record(envelope, Membership) for envelope in envelopes]
    return tuple(member for member in decoded if member is not None)


def datasets_for_eprint(
    eprint_uri: str,
    *,
    appview: str | None = None,
    appview_client: AppviewClient | None = None,
    data_kind: str | None = None,
) -> tuple[DataLink, ...]:
    """List data links that point at an eprint, across all repos.

    Parameters
    ----------
    eprint_uri : str
        The eprint AT-URI to find data links for.
    appview : str or None, optional
        An appview base URL.
    appview_client : AppviewClient or None, optional
        An injected appview client.
    data_kind : str or None, optional
        Restrict to a data-kind slug.

    Returns
    -------
    tuple of lairs.records._generated.eprint.DataLink
        The data-link records that reference the eprint.

    Raises
    ------
    ValueError
        If no appview endpoint or client is available.
    """
    client, owns = _appview_for(appview, appview_client)
    params: QueryParams = {"eprintUri": eprint_uri}
    if data_kind is not None:
        params["dataKind"] = data_kind
    try:
        envelopes = list(client.list("eprint.listDataLinks", params))
    finally:
        if owns:
            client.close()
    decoded = [_decode_record(envelope, DataLink) for envelope in envelopes]
    return tuple(link for link in decoded if link is not None)


def members_of_collection(
    collection_uri: str,
    *,
    appview: str | None = None,
    appview_client: AppviewClient | None = None,
    role: str | None = None,
    member_type: str | None = None,
) -> tuple[catalog_records.Membership, ...]:
    """List the membership edges out of a collection, across all repos.

    Covers both arms of the catalogue model: child collections are reachable by
    ``role="member"`` and produce records by ``role="produce"``. An edge is
    written by the pointing party and lives in that party's repo, so this appview
    query is the only way to see the edges a container does not itself hold.

    Parameters
    ----------
    collection_uri : str
        The container collection AT-URI to list members of.
    appview : str or None, optional
        An appview base URL.
    appview_client : AppviewClient or None, optional
        An injected appview client.
    role : str or None, optional
        Restrict to a membership role slug (for example ``"produce"``).
    member_type : str or None, optional
        Restrict to a member NSID (for example ``"pub.layers.corpus.corpus"``).

    Returns
    -------
    tuple of pub.layers.catalog.Membership
        The membership edge records out of the collection.

    Raises
    ------
    ValueError
        If no appview endpoint or client is available.
    """
    client, owns = _appview_for(appview, appview_client)
    params: QueryParams = {"collection": collection_uri}
    if role is not None:
        params["role"] = role
    if member_type is not None:
        params["memberType"] = member_type
    try:
        envelopes = list(client.list("catalog.listMembers", params))
    finally:
        if owns:
            client.close()
    decoded = [
        _decode_record(envelope, catalog_records.Membership) for envelope in envelopes
    ]
    return tuple(edge for edge in decoded if edge is not None)


def containers_of(
    member_uri: str,
    *,
    appview: str | None = None,
    appview_client: AppviewClient | None = None,
    role: str | None = None,
) -> tuple[catalog_records.Membership, ...]:
    """List the collections that contain, annotate, or point at a record.

    The reverse index over ``pub.layers.catalog.membership``: a hard dependency
    rather than a convenience, because edges are written by the pointing party
    and live in that party's repo, so cross-family structure is invisible from
    the pointed-at record's own side. This is what surfaces "annotated by
    PropBank-SRL" on a treebank whose maintainers never wrote that edge.

    Parameters
    ----------
    member_uri : str
        The AT-URI of the record to find containers for. May be a collection, a
        corpus, an annotation layer, a media item, a judgment set, an ontology,
        or any other member type.
    appview : str or None, optional
        An appview base URL.
    appview_client : AppviewClient or None, optional
        An injected appview client.
    role : str or None, optional
        Restrict to a membership role slug.

    Returns
    -------
    tuple of pub.layers.catalog.Membership
        The membership edge records pointing at the member.

    Raises
    ------
    ValueError
        If no appview endpoint or client is available.
    """
    client, owns = _appview_for(appview, appview_client)
    params: QueryParams = {"member": member_uri}
    if role is not None:
        params["role"] = role
    try:
        envelopes = list(client.list("catalog.listContainers", params))
    finally:
        if owns:
            client.close()
    decoded = [
        _decode_record(envelope, catalog_records.Membership) for envelope in envelopes
    ]
    return tuple(edge for edge in decoded if edge is not None)


class RollupFacetValue(dx.Model):
    """One bucket within a rollup facet dimension.

    Attributes
    ----------
    value : str
        The bucket's slug, rendered verbatim when off-vocabulary.
    count : int
        The number of distinct members contributing this value.
    value_uri : str or None
        The AT-URI of the definition node the bucket resolved to, when any.
    label : str or None
        The display label resolved from the definition node, when any.
    """

    value: str = dx.field(description="the bucket slug")
    count: int = dx.field(description="distinct members contributing this value")
    value_uri: str | None = dx.field(
        default=None,
        description="AT-URI of the definition node the bucket resolved to",
    )
    label: str | None = dx.field(
        default=None,
        description="display label resolved from the definition node",
    )


class RollupFacet(dx.Model):
    """One facet dimension of a rollup and its buckets.

    Attributes
    ----------
    dimension : str
        The facet dimension slug (``language``, ``modality``, ...).
    values : tuple of RollupFacetValue
        The buckets within the dimension, one per distinct value.
    dimension_uri : str or None
        The AT-URI of the facet-dimension definition node, when any.
    """

    dimension: str = dx.field(description="the facet dimension slug")
    values: tuple[dx.Embed[RollupFacetValue], ...] = dx.field(
        default_factory=tuple,
        description="the buckets within the dimension",
    )
    dimension_uri: str | None = dx.field(
        default=None,
        description="AT-URI of the facet-dimension definition node",
    )


class RollupWarning(dx.Model):
    """A qualification on a computed rollup.

    Attributes
    ----------
    code : str
        The warning-code slug (``count-unavailable``, ``pin-dangling``, ...).
    code_uri : str or None
        The AT-URI of the warning-code definition node, when any.
    subject_ref : str or None
        The AT-URI of the record the warning concerns, when any.
    detail : str or None
        Prose explaining the warning for its subject, when any.
    """

    code: str = dx.field(description="the warning-code slug")
    code_uri: str | None = dx.field(
        default=None,
        description="AT-URI of the warning-code definition node",
    )
    subject_ref: str | None = dx.field(
        default=None,
        description="AT-URI of the record the warning concerns",
    )
    detail: str | None = dx.field(
        default=None,
        description="prose explaining the warning for its subject",
    )


class Rollup(dx.Model):
    """Totals and facets computed over a collection's subtree.

    Derived state, so a query result rather than a record: sums traverse the
    containment spine only, so each descendant is counted exactly once; facets
    union over the whole relation graph, so a member reachable by two paths
    contributes once. A total is never presented as firmer than its inputs, which
    is why each total in ``totals`` carries its own ``countSource``.

    Attributes
    ----------
    collection : str
        The AT-URI of the collection the rollup was computed over.
    computed_at : str
        When the rollup was computed; a rollup without a timestamp cannot be told
        from a stale cache.
    descendant_collection_count : int or None
        The number of collections in the subtree along the containment spine.
    totals : tuple of pub.layers.catalog.ContentSummary
        The summed content buckets over the subtree, each with its countSource.
    facets : tuple of RollupFacet
        The facet buckets over the reachable graph.
    warnings : tuple of RollupWarning
        What the rollup could not establish, reported rather than absorbed.
    """

    collection: str = dx.field(description="AT-URI of the rolled-up collection")
    computed_at: str = dx.field(description="when the rollup was computed")
    descendant_collection_count: int | None = dx.field(
        default=None,
        description="collections in the subtree along the containment spine",
    )
    totals: tuple[dx.Embed[catalog_records.ContentSummary], ...] = dx.field(
        default_factory=tuple,
        description="summed content buckets over the subtree",
    )
    facets: tuple[dx.Embed[RollupFacet], ...] = dx.field(
        default_factory=tuple,
        description="facet buckets over the reachable graph",
    )
    warnings: tuple[dx.Embed[RollupWarning], ...] = dx.field(
        default_factory=tuple,
        description="what the rollup could not establish",
    )


def _rollup_totals(
    body: dict[str, JsonValue],
) -> tuple[catalog_records.ContentSummary, ...]:
    """Decode the ``totals`` array of a rollup response into content summaries."""
    raw = body.get("totals")
    if not isinstance(raw, list):
        return ()
    totals: list[catalog_records.ContentSummary] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        payload = {key: value for key, value in item.items() if key != "$type"}
        try:
            totals.append(catalog_records.ContentSummary.model_validate(payload))
        except dx.ValidationError:
            continue
    return tuple(totals)


def _rollup_facets(body: dict[str, JsonValue]) -> tuple[RollupFacet, ...]:
    """Decode the ``facets`` array of a rollup response."""
    raw = body.get("facets")
    if not isinstance(raw, list):
        return ()
    facets: list[RollupFacet] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        if not isinstance(dimension, str):
            continue
        values: list[RollupFacetValue] = []
        raw_values = item.get("values")
        if isinstance(raw_values, list):
            for bucket in raw_values:
                if not isinstance(bucket, dict):
                    continue
                value = bucket.get("value")
                count = bucket.get("count")
                if not isinstance(value, str) or not isinstance(count, int):
                    continue
                uri = bucket.get("valueUri")
                label = bucket.get("label")
                values.append(
                    RollupFacetValue(
                        value=value,
                        count=count,
                        value_uri=uri if isinstance(uri, str) else None,
                        label=label if isinstance(label, str) else None,
                    ),
                )
        dimension_uri = item.get("dimensionUri")
        facets.append(
            RollupFacet(
                dimension=dimension,
                values=tuple(values),
                dimension_uri=dimension_uri if isinstance(dimension_uri, str) else None,
            ),
        )
    return tuple(facets)


def _rollup_warnings(body: dict[str, JsonValue]) -> tuple[RollupWarning, ...]:
    """Decode the ``warnings`` array of a rollup response."""
    raw = body.get("warnings")
    if not isinstance(raw, list):
        return ()
    warnings: list[RollupWarning] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if not isinstance(code, str):
            continue
        code_uri = item.get("codeUri")
        subject_ref = item.get("subjectRef")
        detail = item.get("detail")
        warnings.append(
            RollupWarning(
                code=code,
                code_uri=code_uri if isinstance(code_uri, str) else None,
                subject_ref=subject_ref if isinstance(subject_ref, str) else None,
                detail=detail if isinstance(detail, str) else None,
            ),
        )
    return tuple(warnings)


def rollup_of_collection(
    collection_uri: str,
    *,
    appview: str | None = None,
    appview_client: AppviewClient | None = None,
    max_depth: int | None = None,
    include_facets: bool = True,
) -> Rollup:
    """Compute totals and facets over a collection's subtree, across all repos.

    A read-only appview query (``catalog.getRollup``) consumed authoritatively:
    the appview owns the arithmetic because a record asserting counts over records
    its author does not own is neither rebuildable from the firehose nor
    authoritative. Sums walk the containment spine; facets union the relation
    graph.

    Parameters
    ----------
    collection_uri : str
        The collection AT-URI to roll up.
    appview : str or None, optional
        An appview base URL.
    appview_client : AppviewClient or None, optional
        An injected appview client.
    max_depth : int or None, optional
        Limit the subtree walk to this many levels below the collection.
    include_facets : bool, optional
        Whether to request the facet buckets; sums alone are cheaper.

    Returns
    -------
    Rollup
        The computed totals, facets, and warnings.

    Raises
    ------
    ValueError
        If no appview endpoint or client is available.
    """
    client, owns = _appview_for(appview, appview_client)
    params: QueryParams = {"collection": collection_uri}
    if max_depth is not None:
        params["maxDepth"] = max_depth
    if not include_facets:
        params["includeFacets"] = False
    try:
        body = client.query("catalog.getRollup", params)
    finally:
        if owns:
            client.close()
    collection = body.get("collection")
    computed_at = body.get("computedAt")
    descendant = body.get("descendantCollectionCount")
    return Rollup(
        collection=collection if isinstance(collection, str) else collection_uri,
        computed_at=computed_at if isinstance(computed_at, str) else "",
        descendant_collection_count=descendant if isinstance(descendant, int) else None,
        totals=_rollup_totals(body),
        facets=_rollup_facets(body),
        warnings=_rollup_warnings(body),
    )
