"""The catalogue-collection surface: a tree of citable collections.

A :class:`Collection` exposes the browsable, citable artifact for a dataset as a
whole: a ``pub.layers.catalog.collection`` record plus the containment tree and
membership edges reachable from it. The graph is held in a
:class:`lairs.store.pool.ModelPool` keyed by AT-URI, so cross-refs (a child's
``parentRef``, a membership edge's ``catalogRef`` and ``member``) resolve to
model instances.

Container-ness is a collection kind, not a separate record type, so a collection
may hold other collections to arbitrary depth. The containment spine is the
child-held single-valued ``parentRef``; :meth:`children` selects the direct
children and :meth:`subtree` the whole subtree by the denormalized ``rootRef``.
Membership edge records (``pub.layers.catalog.membership``) carry the produces and
cross-family relations: :meth:`produces` and :meth:`members` split them by
``role``.

Loading dispatches on a source. The ``pds`` source enumerates the collection
authority's catalogue collections and membership edges through a PDS client and
follows every AT-URI reference across account boundaries; the ``appview`` source
uses the appview query API (``catalog.getCollection`` plus ``catalog.listMembers``).
This mirrors :func:`lairs.data.corpus.load_corpus` and keys the collection load on
its own NSID map, so a corpus load never enumerates collections and a collection
load never enumerates a corpus's expressions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.data._loader import decode_envelope, load_graph
from lairs.data.dataset import Dataset
from lairs.records._generated import catalog as catalog_records
from lairs.store.pool import ModelPool

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lairs._types import JsonValue
    from lairs.atproto.appview import AppviewClient
    from lairs.atproto.pds import PdsClient
    from lairs.data._loader import PdsSource

__all__ = ["Collection", "load_collection"]

# the collection NSIDs the collection surface joins over.
_CATALOG_COLLECTION_NSID = "pub.layers.catalog.collection"
_CATALOG_MEMBERSHIP_NSID = "pub.layers.catalog.membership"

# the record model class for each collection NSID. Deliberately narrow: a
# collection load enumerates only the catalogue record types, never a corpus's
# expressions or a session's participants, which the produce edges reference by
# AT-URI and a caller resolves with the relevant surface when it needs them.
_NSID_MODELS: dict[str, type[dx.Model]] = {
    _CATALOG_COLLECTION_NSID: catalog_records.Collection,
    _CATALOG_MEMBERSHIP_NSID: catalog_records.Membership,
}

# the membership roles that split a collection's edges. Only these two contribute
# to a rollup; every other role is a rendered-but-never-summed cross-family
# relation (see pub.layers.catalog.membership#role).
_ROLE_MEMBER = "member"
_ROLE_PRODUCE = "produce"

# the recognised load sources, mirroring load_corpus.
_SOURCE_PDS = "pds"
_SOURCE_APPVIEW = "appview"
_SOURCE_AUTO = "auto"
_VALID_SOURCES = frozenset({_SOURCE_PDS, _SOURCE_APPVIEW, _SOURCE_AUTO})

# the appview query NSIDs the appview load path calls.
_GET_COLLECTION_NSID = "catalog.getCollection"
_LIST_MEMBERS_NSID = "catalog.listMembers"


class Collection:
    """A tree of catalogue collections joined by AT-URI cross-references.

    Parameters
    ----------
    pool : lairs.store.pool.ModelPool or None, optional
        A pre-populated pool of records keyed by AT-URI. When omitted an empty
        pool is created.
    uri : str or None, optional
        The AT-URI of the backing collection record, when loaded from one.

    Attributes
    ----------
    pool : lairs.store.pool.ModelPool
        The AT-URI-keyed record graph.
    uri : str or None
        The collection record AT-URI, if any.
    """

    def __init__(
        self,
        pool: ModelPool | None = None,
        *,
        uri: str | None = None,
    ) -> None:
        self.pool = pool if pool is not None else ModelPool()
        self.uri = uri

    @classmethod
    def new(cls, uri: str | None = None) -> Collection:
        """Create an empty collection surface for authoring.

        Parameters
        ----------
        uri : str or None, optional
            An AT-URI to associate with the collection record.

        Returns
        -------
        Collection
            A new, empty collection surface.
        """
        return cls(uri=uri)

    def _collections(self) -> Iterator[tuple[str, catalog_records.Collection]]:
        """Yield ``(uri, record)`` pairs for every collection record in the pool."""
        for ref in self.pool.uris():
            model = self.pool.get(ref)
            if isinstance(model, catalog_records.Collection):
                yield ref, model

    def _memberships(self) -> Iterator[catalog_records.Membership]:
        """Yield the membership edges whose ``catalogRef`` is this collection.

        When :attr:`uri` is set only edges pointing at it are yielded; otherwise
        every membership in the pool is yielded.
        """
        for ref in self.pool.uris():
            model = self.pool.get(ref)
            if not isinstance(model, catalog_records.Membership):
                continue
            if self.uri is not None and model.catalogRef != self.uri:
                continue
            yield model

    @property
    def collection_record(self) -> catalog_records.Collection | None:
        """Return the backing collection record, if one is loaded.

        Returns
        -------
        pub.layers.catalog.Collection or None
            The record looked up at :attr:`uri`, or ``None`` when the surface has
            no AT-URI or no collection record was loaded for it.
        """
        if self.uri is None:
            return None
        model = self.pool.get(self.uri)
        return model if isinstance(model, catalog_records.Collection) else None

    def collections(self) -> Dataset[catalog_records.Collection]:
        """Return every collection record in the pool.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of collection records, in pool order.
        """
        return Dataset(
            [model for _, model in self._collections()],
            model=catalog_records.Collection,
        )

    def children(self) -> Dataset[catalog_records.Collection]:
        """Return the direct children of this collection.

        A child is a collection whose single-valued ``parentRef`` points at this
        collection's AT-URI, the canonical containment spine.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of the direct-child collection records, in pool order.
        """
        records = [
            model
            for _, model in self._collections()
            if self.uri is not None and model.parentRef == self.uri
        ]
        return Dataset(records, model=catalog_records.Collection)

    def subtree(self) -> Dataset[catalog_records.Collection]:
        """Return every collection in this collection's containment subtree.

        A subtree member is a collection whose denormalized ``rootRef`` equals
        this collection's AT-URI, so subtree selection is an equality rather than
        a recursive chase.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of the subtree collection records, in pool order.
        """
        records = [
            model
            for _, model in self._collections()
            if self.uri is not None and model.rootRef == self.uri
        ]
        return Dataset(records, model=catalog_records.Collection)

    def memberships(self) -> Dataset[catalog_records.Membership]:
        """Return the membership edges out of this collection.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of the membership edge records, in pool order.
        """
        return Dataset(
            list(self._memberships()),
            model=catalog_records.Membership,
        )

    def members(self) -> Dataset[catalog_records.Membership]:
        """Return the nested-collection (``member``) edges out of this collection.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of the ``role == member`` edges, in pool order.
        """
        records = [edge for edge in self._memberships() if edge.role == _ROLE_MEMBER]
        return Dataset(records, model=catalog_records.Membership)

    def produces(self) -> Dataset[catalog_records.Membership]:
        """Return the produce edges out of this collection.

        A produce edge names a corpus, annotation layer, segmentation, alignment,
        judgment set, media item, or ontology this collection publishes; it is
        where a rollup's count recursion bottoms out.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of the ``role == produce`` edges, in pool order.
        """
        records = [edge for edge in self._memberships() if edge.role == _ROLE_PRODUCE]
        return Dataset(records, model=catalog_records.Membership)

    def contents(self) -> tuple[catalog_records.ContentSummary, ...]:
        """Return the collection's publisher-declared content summary buckets.

        Returns
        -------
        tuple of pub.layers.catalog.ContentSummary
            The content buckets on the backing collection record, one per produce
            type and narrowing, or the empty tuple when none are declared.
        """
        record = self.collection_record
        if record is None or record.contents is None:
            return ()
        return tuple(record.contents)

    @property
    def citation(self) -> catalog_records.Citation | None:
        """Return the collection's citation block, if it declares one.

        Presence of a citation block marks this node as a citable level.

        Returns
        -------
        pub.layers.catalog.Citation or None
            The citation block, or ``None`` when the collection is not citable or
            no record is loaded.
        """
        record = self.collection_record
        return record.citation if record is not None else None

    def add_record(self, uri: str, record: dx.Model) -> None:
        """Add any catalogue record to the collection graph by AT-URI.

        Parameters
        ----------
        uri : str
            The AT-URI of the record.
        record : didactic.api.Model
            The record to add (a collection or a membership edge).
        """
        self.pool.add(uri, record)


def _load_from_pds(
    uri: str,
    client: PdsSource,
    *,
    follow_refs: bool = True,
) -> Collection:
    """Load a collection tree from a PDS, following refs across accounts.

    Parameters
    ----------
    uri : str
        The collection AT-URI whose authority is enumerated.
    client : lairs.data._loader.PdsSource
        The PDS source to read through.
    follow_refs : bool, optional
        Whether to follow AT-URI references into other accounts.

    Returns
    -------
    Collection
        The loaded collection tree.
    """
    pool = load_graph(uri, _NSID_MODELS, client, follow_refs=follow_refs)
    return Collection(pool, uri=uri)


def _add_collection_view(pool: ModelPool, view: JsonValue) -> None:
    """Decode a collectionView's ``value`` into the pool by its ``uri``.

    A ``collectionView`` (from ``catalog.getCollection``) is a ``{uri, cid,
    value, ...}`` object whose ``value`` is the collection record. A view that is
    not an object, carries no string ``uri``, or fails to decode is skipped.

    Parameters
    ----------
    pool : lairs.store.pool.ModelPool
        The pool to add the decoded collection to.
    view : JsonValue
        A raw collectionView object from an appview response.
    """
    if not isinstance(view, dict):
        return
    view_uri = view.get("uri")
    value = view.get("value")
    if not isinstance(view_uri, str) or not isinstance(value, dict):
        return
    payload = {key: item for key, item in value.items() if key != "$type"}
    # validate through the JSON validator, not model_validate: a record fetched
    # over XRPC carries datetimes as JSON strings, which the JSON validator
    # coerces but the in-memory dict validator does not.
    try:
        record = catalog_records.Collection.model_validate_json(json.dumps(payload))
    except dx.ValidationError:
        return
    pool.add(view_uri, record)


def _load_from_appview(uri: str, client: AppviewClient) -> Collection:
    """Load a collection tree from the appview query API.

    Fetches the collection through ``catalog.getCollection`` (with its ancestors
    and immediate children) and its membership edges through
    ``catalog.listMembers``, building the same AT-URI-keyed pool the PDS path
    builds. A member's own record is not fetched here; the membership edge and,
    for nested collections, the ``getCollection`` children carry what a listing
    needs.

    Parameters
    ----------
    uri : str
        The collection AT-URI to fetch.
    client : lairs.atproto.appview.AppviewClient
        The appview client to query through.

    Returns
    -------
    Collection
        The loaded collection tree.
    """
    pool = ModelPool()
    body = client.query(_GET_COLLECTION_NSID, {"uri": uri})
    _add_collection_view(pool, {"uri": uri, "value": body.get("value")})
    for key in ("ancestors", "children"):
        views = body.get(key)
        if isinstance(views, list):
            for view in views:
                _add_collection_view(pool, view)
    for envelope in client.list(_LIST_MEMBERS_NSID, {"collection": uri}):
        decoded = decode_envelope(envelope, _NSID_MODELS)
        if decoded is not None:
            pool.add(*decoded)
    return Collection(pool, uri=uri)


def load_collection(  # noqa: PLR0913  (the loader threads several optional knobs)
    uri: str,
    *,
    source: str = "auto",
    cache_dir: str | None = None,
    revision: str | None = None,
    pds_client: PdsClient | None = None,
    appview_client: AppviewClient | None = None,
    follow_refs: bool = True,
) -> Collection:
    """Load a catalogue collection by AT-URI from a PDS or the appview.

    A collection is the citable, browsable artifact for a dataset as a whole. The
    ``pds`` source enumerates the collection authority's catalogue records and
    follows every AT-URI reference across account boundaries, transitively, to
    pull in the containment tree and membership edges; the ``appview`` source uses
    ``catalog.getCollection`` plus ``catalog.listMembers``. Under ``auto`` the PDS
    path is taken when a ``pds_client`` is injected, otherwise the appview path
    when an ``appview_client`` is. A client may be injected for testing without
    network setup.

    Parameters
    ----------
    uri : str
        The collection AT-URI (its authority is enumerated on the PDS path).
    source : str, optional
        The source to load from (``"pds"``, ``"appview"``, or ``"auto"``).
    cache_dir : str or None, optional
        A local cache directory (reserved; not yet used).
    revision : str or None, optional
        A revision to resolve (reserved; not yet used).
    pds_client : lairs.atproto.pds.PdsClient or None, optional
        An injected PDS client, required for the ``pds`` source.
    appview_client : lairs.atproto.appview.AppviewClient or None, optional
        An injected appview client, required for the ``appview`` source.
    follow_refs : bool, optional
        Whether to follow AT-URI references across account boundaries on the PDS
        path. Defaults to ``True``.

    Returns
    -------
    Collection
        The loaded collection tree.

    Raises
    ------
    ValueError
        When ``source`` is not a recognised source value.
    NotImplementedError
        When the requested source has no injected client to read through.
    """
    if source not in _VALID_SOURCES:
        valid = sorted(_VALID_SOURCES)
        msg = f"unknown collection source {source!r}; expected one of {valid}"
        raise ValueError(msg)
    _ = (cache_dir, revision)
    if source in {_SOURCE_PDS, _SOURCE_AUTO} and pds_client is not None:
        return _load_from_pds(uri, pds_client, follow_refs=follow_refs)
    if source in {_SOURCE_APPVIEW, _SOURCE_AUTO} and appview_client is not None:
        return _load_from_appview(uri, appview_client)
    if source == _SOURCE_APPVIEW:
        msg = "appview collection loading requires an injected appview_client"
        raise NotImplementedError(msg)
    msg = "collection loading needs an injected pds_client or appview_client"
    raise NotImplementedError(msg)
