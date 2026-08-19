"""Collection-to-summary mapping and collection filtering.

Projects a generated ``Collection`` record (or a record envelope carrying one)
into the flat ``CollectionSummary`` discovery shape, evaluates a
``CollectionFilter`` over a summary, and extracts the server-side facets
``catalog.listCollections`` supports. This is the catalogue-collection parallel
to :mod:`lairs.discovery.summary`, added additively so the corpus path, which
keys on the scalar ``_CORPUS_NSID``, is never touched.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs._aturi import authority_of, nsid_of
from lairs.discovery.models import CollectionSummary
from lairs.discovery.summary import _license_facet
from lairs.records._generated import catalog as catalog_records

if TYPE_CHECKING:
    from lairs._types import JsonValue
    from lairs.atproto.pds import QueryParams, RecordEnvelope
    from lairs.discovery.models import CollectionFilter

__all__ = [
    "collection_from_value",
    "listcollections_params",
    "matches",
    "summary_from_collection",
    "summary_from_envelope",
]

_CATALOG_COLLECTION_NSID = "pub.layers.catalog.collection"
"""The collection NSID of a catalogue collection record."""

# the creditPolicy values that mark a collection as a citable level.
_CITABLE_POLICIES = frozenset({"cite-self", "cite-both"})


def _is_citable(citation: catalog_records.Citation | None) -> bool:
    """Return whether a citation block marks this collection as citable.

    A collection is citable when it declares a citation block whose credit
    policy lands the citation on itself (``cite-self`` or ``cite-both``), which
    is what lets UD name the treebank as citable while UniMorph names the project.

    Parameters
    ----------
    citation : pub.layers.catalog.Citation or None
        The collection's citation block.

    Returns
    -------
    bool
        ``True`` when the collection declares itself the level to cite.
    """
    return citation is not None and citation.creditPolicy in _CITABLE_POLICIES


def _content_facets(
    contents: tuple[catalog_records.ContentSummary, ...] | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Project a collection's content buckets into flat modality/subkind/method sets.

    The distinct, sorted slugs let a listing facet on ``modality``,
    ``annotation-subkind``, and ``source-method`` (the primary NLP browse
    criteria) without paging the collection's produces.

    Parameters
    ----------
    contents : tuple of pub.layers.catalog.ContentSummary or None
        The collection's declared content buckets.

    Returns
    -------
    tuple
        The ``(modalities, annotation_subkinds, source_methods)`` slug tuples.
    """
    modalities: set[str] = set()
    subkinds: set[str] = set()
    methods: set[str] = set()
    for bucket in contents or ():
        if bucket.modality is not None:
            modalities.add(bucket.modality)
        if bucket.subkind is not None:
            subkinds.add(bucket.subkind)
        if bucket.sourceMethod is not None:
            methods.add(bucket.sourceMethod)
    return (
        tuple(sorted(modalities)),
        tuple(sorted(subkinds)),
        tuple(sorted(methods)),
    )


def summary_from_collection(  # noqa: PLR0913  (a projection threads identity, source, and edge counts)
    collection: catalog_records.Collection,
    *,
    uri: str,
    did: str,
    handle: str | None = None,
    source_endpoint: str | None = None,
    member_count: int | None = None,
    produce_count: int | None = None,
) -> CollectionSummary:
    """Project a collection record into a ``CollectionSummary``.

    ``member_count`` and ``produce_count`` are not carried by the record itself
    (membership edges live in other repos), so a caller that has counted the
    edges, or holds the appview's collection view, supplies them; they default to
    ``None`` when unknown.

    Parameters
    ----------
    collection : pub.layers.catalog.Collection
        The collection record to project.
    uri : str
        The collection AT-URI.
    did : str
        The owning repository DID.
    handle : str or None, optional
        The owning handle, when known.
    source_endpoint : str or None, optional
        The PDS or appview the collection was read from.
    member_count : int or None, optional
        The number of nested-collection (``member``) edges, when counted.
    produce_count : int or None, optional
        The number of produce edges, when counted.

    Returns
    -------
    CollectionSummary
        The flat discovery summary.
    """
    modalities, subkinds, methods = _content_facets(collection.contents)
    return CollectionSummary(
        uri=uri,
        did=did,
        name=collection.name,
        kind=collection.kind,
        handle=handle,
        description=collection.description,
        kind_uri=collection.kindUri,
        languages=collection.languages or (),
        license=_license_facet(collection.licensing),
        access=collection.access,
        stability=collection.stability,
        depth=collection.depth,
        parent_ref=collection.parentRef,
        root_ref=collection.rootRef,
        citable=_is_citable(collection.citation),
        member_count=member_count,
        produce_count=produce_count,
        version=collection.version,
        modalities=modalities,
        annotation_subkinds=subkinds,
        source_methods=methods,
        created_at=collection.createdAt.isoformat(),
        eprint_refs=collection.eprintRefs or (),
        source_endpoint=source_endpoint,
    )


def collection_from_value(value: JsonValue) -> catalog_records.Collection | None:
    """Decode a record value into a ``Collection``, or ``None`` on failure.

    The wire-only ``$type`` discriminator is dropped before validation, since the
    generated models do not declare it.

    Parameters
    ----------
    value : JsonValue
        The record value to decode.

    Returns
    -------
    pub.layers.catalog.Collection or None
        The decoded collection, or ``None`` when the value is not a decodable
        collection.
    """
    if not isinstance(value, dict):
        return None
    payload = {key: item for key, item in value.items() if key != "$type"}
    try:
        return catalog_records.Collection.model_validate_json(json.dumps(payload))
    except dx.ValidationError:
        return None


def summary_from_envelope(  # noqa: PLR0913  (a decode threads identity, source, and edge counts)
    envelope: RecordEnvelope,
    *,
    did: str | None = None,
    handle: str | None = None,
    source_endpoint: str | None = None,
    member_count: int | None = None,
    produce_count: int | None = None,
) -> CollectionSummary | None:
    """Decode a collection envelope into a ``CollectionSummary``.

    Returns ``None`` when the envelope is not a collection record or its value
    does not validate, so a single bad record does not abort a listing.

    Parameters
    ----------
    envelope : lairs.atproto.pds.RecordEnvelope
        The record envelope to decode.
    did : str or None, optional
        The owning DID; derived from the envelope URI when omitted.
    handle : str or None, optional
        The owning handle, when known.
    source_endpoint : str or None, optional
        The PDS or appview the envelope was read from.
    member_count : int or None, optional
        The number of nested-collection edges, when counted.
    produce_count : int or None, optional
        The number of produce edges, when counted.

    Returns
    -------
    CollectionSummary or None
        The summary, or ``None`` when the record is not a decodable collection.
    """
    if nsid_of(envelope.uri) != _CATALOG_COLLECTION_NSID:
        return None
    collection = collection_from_value(envelope.value)
    if collection is None:
        return None
    resolved_did = did if did is not None else authority_of(envelope.uri)
    return summary_from_collection(
        collection,
        uri=envelope.uri,
        did=resolved_did,
        handle=handle,
        source_endpoint=source_endpoint,
        member_count=member_count,
        produce_count=produce_count,
    )


def _any_in(wanted: tuple[str, ...], present: tuple[str, ...]) -> bool:
    """Return whether an array facet is satisfied by a summary's array field.

    An unset facet (empty ``wanted``) passes; otherwise at least one wanted slug
    must be present.
    """
    return not wanted or bool(set(wanted) & set(present))


def _scalar_in(wanted: tuple[str, ...], value: str | None) -> bool:
    """Return whether a scalar summary value is any of an array facet's alternatives."""
    return not wanted or value in wanted


def matches(summary: CollectionSummary, flt: CollectionFilter | None) -> bool:
    """Return whether a collection summary satisfies a filter.

    Parameters
    ----------
    summary : CollectionSummary
        The summary to test.
    flt : CollectionFilter or None
        The filter; ``None`` matches everything.

    Returns
    -------
    bool
        ``True`` when the summary passes every set facet.
    """
    if flt is None:
        return True
    haystack = f"{summary.name} {summary.description or ''}".lower()
    return all(
        (
            _scalar_in(flt.kind, summary.kind),
            _scalar_in(flt.kind_uri, summary.kind_uri),
            flt.parent_ref is None or flt.parent_ref == summary.parent_ref,
            flt.root_ref is None or flt.root_ref == summary.root_ref,
            flt.depth is None or flt.depth == summary.depth,
            not flt.citable_only or summary.citable,
            _any_in(flt.languages, summary.languages),
            _any_in(flt.modality, summary.modalities),
            _any_in(flt.annotation_subkind, summary.annotation_subkinds),
            _any_in(flt.source_method, summary.source_methods),
            _scalar_in(flt.spdx, summary.license),
            _scalar_in(flt.access, summary.access),
            _scalar_in(flt.stability, summary.stability),
            flt.text is None or flt.text.lower() in haystack,
        ),
    )


def listcollections_params(repo: str, flt: CollectionFilter | None) -> QueryParams:
    """Build ``listCollections`` query parameters, pushing the server-side facets.

    The scalar facets (``q``, ``parentRef``, ``rootRef``, ``depth``,
    ``citableOnly``, ``sort``) map cleanly to scalar query parameters and are
    pushed; the array facets (kind, languages, modality, and the rest) are applied
    client-side over the mapped summaries by :func:`matches`, mirroring how
    ``listcorpora_params`` pushes only ``language`` and ``domain``.

    Parameters
    ----------
    repo : str
        The repository DID or handle to list.
    flt : CollectionFilter or None
        The filter whose server-side facets to push.

    Returns
    -------
    QueryParams
        The query parameters for ``catalog.listCollections``.
    """
    params: QueryParams = {"repo": repo}
    if flt is not None:
        if flt.text is not None:
            params["q"] = flt.text
        if flt.parent_ref is not None:
            params["parentRef"] = flt.parent_ref
        if flt.root_ref is not None:
            params["rootRef"] = flt.root_ref
        if flt.depth is not None:
            params["depth"] = flt.depth
        if flt.citable_only:
            params["citableOnly"] = True
        if flt.sort is not None:
            params["sort"] = flt.sort
    return params
