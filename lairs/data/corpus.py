"""The corpus surface: a graph of records joined by AT-URIs.

A ``Corpus`` exposes dataset views (expressions, annotation layers) over the
graph of Layers records, plus authoring and persistence entry points. The graph
is held in a :class:`lairs.store.pool.ModelPool` keyed by AT-URI, so cross-refs
(an annotation layer's ``expression``, an expression's ``mediaRef``, a
segmentation's ``expression``) resolve to model instances. The join helpers walk
those refs to group related records per expression.

Membership records (``pub.layers.corpus.membership``) tie an expression to a
corpus via ``corpusRef`` and carry an optional ``split`` slug. When the pool
holds membership records for this corpus, the expression views and joins are
restricted to the expressions those memberships reference, so loading one corpus
from an authority that hosts several does not bleed the others' expressions in.
When no membership records are present (for example a freshly authored corpus
built only through the ``add_*`` helpers) every pooled expression is treated as a
member, which keeps direct authoring ergonomic.

Loading dispatches on a source. The ``pds`` source enumerates the relevant
collections of an authority's repository through a PDS client; the ``appview``
source uses the appview query API; ``auto`` prefers the appview and falls back to
the PDS. A client may be injected for testing without network access.

The record :class:`pub.layers.corpus.Corpus` model is imported qualified as
``corpus_records.Corpus`` to avoid clashing with the dataset-surface
:class:`Corpus` defined here.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.data.dataset import Dataset
from lairs.records._generated import annotation as annotation_records
from lairs.records._generated import corpus as corpus_records
from lairs.records._generated import expression as expression_records
from lairs.records._generated import media as media_records
from lairs.records._generated import segmentation as segmentation_records
from lairs.records.blobref import normalize_blob_refs
from lairs.store.arrow import annotations_table, expressions_table, materialize
from lairs.store.pool import ModelPool
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lairs.atproto.pds import PdsClient, RecordEnvelope

__all__ = [
    "Corpus",
    "ExpressionWithAnnotations",
    "ExpressionWithMedia",
    "ExpressionWithSegmentation",
    "load_corpus",
]

# the collection NSIDs of the Layers record types a corpus joins over.
_EXPRESSION_NSID = "pub.layers.expression.expression"
_ANNOTATION_LAYER_NSID = "pub.layers.annotation.annotationLayer"
_SEGMENTATION_NSID = "pub.layers.segmentation.segmentation"
_MEDIA_NSID = "pub.layers.media.media"
_CORPUS_NSID = "pub.layers.corpus.corpus"
_MEMBERSHIP_NSID = "pub.layers.corpus.membership"

# the record model class for each corpus collection NSID.
_NSID_MODELS: dict[str, type[dx.Model]] = {
    _EXPRESSION_NSID: expression_records.Expression,
    _ANNOTATION_LAYER_NSID: annotation_records.AnnotationLayer,
    _SEGMENTATION_NSID: segmentation_records.Segmentation,
    _MEDIA_NSID: media_records.Media,
    _CORPUS_NSID: corpus_records.Corpus,
    _MEMBERSHIP_NSID: corpus_records.Membership,
}

# the recognised load sources.
_SOURCE_PDS = "pds"
_SOURCE_APPVIEW = "appview"
_SOURCE_AUTO = "auto"
_VALID_SOURCES = frozenset({_SOURCE_PDS, _SOURCE_APPVIEW, _SOURCE_AUTO})


class ExpressionWithAnnotations(dx.Model):
    """An expression joined to its annotation layers.

    Attributes
    ----------
    expression : pub.layers.expression.Expression
        The expression record.
    uri : str
        The AT-URI of the expression.
    annotation_layers : tuple of pub.layers.annotation.AnnotationLayer
        The annotation layers whose ``expression`` ref points at this one.
    """

    expression: expression_records.Expression = dx.field(
        description="the joined expression record",
    )
    uri: str = dx.field(description="AT-URI of the expression")
    annotation_layers: tuple[annotation_records.AnnotationLayer, ...] = dx.field(
        default_factory=tuple,
        description="annotation layers pointing at this expression",
    )


class ExpressionWithMedia(dx.Model):
    """An expression joined to its media record.

    Attributes
    ----------
    expression : pub.layers.expression.Expression
        The expression record.
    uri : str
        The AT-URI of the expression.
    media : pub.layers.media.Media or None
        The media record referenced by the expression's ``mediaRef``, if loaded.
    """

    expression: expression_records.Expression = dx.field(
        description="the joined expression record",
    )
    uri: str = dx.field(description="AT-URI of the expression")
    media: media_records.Media | None = dx.field(
        default=None,
        description="media record referenced by the expression, if resolved",
    )


class ExpressionWithSegmentation(dx.Model):
    """An expression joined to its segmentation records.

    Attributes
    ----------
    expression : pub.layers.expression.Expression
        The expression record.
    uri : str
        The AT-URI of the expression.
    segmentations : tuple of pub.layers.segmentation.Segmentation
        The segmentations whose ``expression`` ref points at this one.
    """

    expression: expression_records.Expression = dx.field(
        description="the joined expression record",
    )
    uri: str = dx.field(description="AT-URI of the expression")
    segmentations: tuple[segmentation_records.Segmentation, ...] = dx.field(
        default_factory=tuple,
        description="segmentations pointing at this expression",
    )


def _nsid_of(uri: str) -> str:
    """Return the collection NSID embedded in an AT-URI.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The collection segment, or the empty string when none is present.
    """
    body = uri.removeprefix("at://")
    parts = body.split("/")
    minimum_parts_with_collection = 2
    if len(parts) >= minimum_parts_with_collection:
        return parts[1]
    return ""


class Corpus:
    """A graph of Layers records joined by AT-URI cross-references.

    Parameters
    ----------
    pool : lairs.store.pool.ModelPool or None, optional
        A pre-populated pool of records keyed by AT-URI. When omitted an empty
        pool is created and records may be added through the authoring helpers.
    uri : str or None, optional
        The AT-URI of the backing corpus record, when the corpus was loaded from
        one.

    Attributes
    ----------
    pool : lairs.store.pool.ModelPool
        The AT-URI-keyed record graph.
    uri : str or None
        The corpus record AT-URI, if any.
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
    def new(cls, uri: str | None = None) -> Corpus:
        """Create an empty corpus for authoring.

        Parameters
        ----------
        uri : str or None, optional
            An AT-URI to associate with the corpus record.

        Returns
        -------
        Corpus
            A new, empty corpus.
        """
        return cls(uri=uri)

    # graph access -------------------------------------------------------------

    def _models_of(self, nsid: str) -> Iterator[tuple[str, dx.Model]]:
        """Yield ``(uri, model)`` pairs for records of a collection NSID.

        Parameters
        ----------
        nsid : str
            The collection NSID to select.

        Yields
        ------
        tuple of (str, didactic.api.Model)
            The AT-URI and model of each record of that collection.
        """
        for ref in self.pool.uris():
            if _nsid_of(ref) == nsid:
                model = self.pool.get(ref)
                if model is not None:
                    yield ref, model

    def _memberships(self) -> Iterator[corpus_records.Membership]:
        """Yield the membership records that bind expressions to this corpus.

        When :attr:`uri` is set only memberships whose ``corpusRef`` equals it
        are yielded; otherwise every membership in the pool is yielded.

        Yields
        ------
        pub.layers.corpus.Membership
            The membership records tying expressions to this corpus.
        """
        for _, model in self._models_of(_MEMBERSHIP_NSID):
            if not isinstance(model, corpus_records.Membership):
                continue
            if self.uri is not None and model.corpusRef != self.uri:
                continue
            yield model

    def _member_uris(self) -> frozenset[str] | None:
        """Return the expression AT-URIs that are members of this corpus.

        Returns
        -------
        frozenset of str or None
            The set of member expression AT-URIs drawn from the corpus's
            membership records, or ``None`` when the pool holds no membership
            record for this corpus (in which case every pooled expression is
            treated as a member).
        """
        members = {membership.expressionRef for membership in self._memberships()}
        return frozenset(members) if members else None

    def _member_expressions(
        self,
    ) -> Iterator[tuple[str, expression_records.Expression]]:
        """Yield ``(uri, expression)`` pairs for the corpus member expressions.

        Expressions not bound to this corpus by a membership record are skipped
        when any membership exists; otherwise every pooled expression is yielded.

        Yields
        ------
        tuple of (str, pub.layers.expression.Expression)
            The AT-URI and expression model of each member.
        """
        members = self._member_uris()
        for uri, model in self._models_of(_EXPRESSION_NSID):
            if not isinstance(model, expression_records.Expression):
                continue
            if members is not None and uri not in members:
                continue
            yield uri, model

    @property
    def expressions(self) -> Dataset[expression_records.Expression]:
        """Return a dataset of the corpus member expressions.

        When the pool holds membership records for this corpus only the
        expressions those memberships reference are returned; otherwise every
        pooled expression is returned.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of expression models, in pool order.
        """
        records = [model for _, model in self._member_expressions()]
        return Dataset(records, model=expression_records.Expression)

    def expression_uris(self) -> list[str]:
        """Return the AT-URIs of the corpus member expressions.

        Returns
        -------
        list of str
            The member expression AT-URIs, in pool order.
        """
        return [uri for uri, _ in self._member_expressions()]

    def annotation_layers(
        self,
        *,
        kind: str | None = None,
        subkind: str | None = None,
    ) -> Dataset[annotation_records.AnnotationLayer]:
        """Return a dataset of annotation layers, optionally filtered.

        Parameters
        ----------
        kind : str or None, optional
            An annotation-layer kind filter (for example ``"token-tag"``).
        subkind : str or None, optional
            An annotation-layer subkind filter (for example ``"pos"``).

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of annotation-layer models matching the filters.
        """
        records: list[annotation_records.AnnotationLayer] = []
        for _, model in self._models_of(_ANNOTATION_LAYER_NSID):
            if not isinstance(model, annotation_records.AnnotationLayer):
                continue
            if kind is not None and model.kind != kind:
                continue
            if subkind is not None and model.subkind != subkind:
                continue
            records.append(model)
        return Dataset(records, model=annotation_records.AnnotationLayer)

    def segmentations(self) -> Dataset[segmentation_records.Segmentation]:
        """Return a dataset of the corpus segmentations.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of segmentation models, in pool order.
        """
        records = [
            model
            for _, model in self._models_of(_SEGMENTATION_NSID)
            if isinstance(model, segmentation_records.Segmentation)
        ]
        return Dataset(records, model=segmentation_records.Segmentation)

    def media(self) -> Dataset[media_records.Media]:
        """Return a dataset of the corpus media records.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of media models, in pool order.
        """
        records = [
            model
            for _, model in self._models_of(_MEDIA_NSID)
            if isinstance(model, media_records.Media)
        ]
        return Dataset(records, model=media_records.Media)

    def memberships(self) -> Dataset[corpus_records.Membership]:
        """Return a dataset of the corpus membership records.

        Each membership ties an expression to this corpus via ``corpusRef`` and
        may carry a ``split`` slug and an ``ordinal``. When :attr:`uri` is set
        only the memberships whose ``corpusRef`` equals it are returned.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of membership models, in pool order.
        """
        return Dataset(
            list(self._memberships()),
            model=corpus_records.Membership,
        )

    @property
    def corpus_record(self) -> corpus_records.Corpus | None:
        """Return the backing corpus record, if one is loaded.

        The record is looked up in the pool at :attr:`uri`; it is ``None`` when
        the corpus has no AT-URI or when no corpus record was loaded for it.

        Returns
        -------
        pub.layers.corpus.Corpus or None
            The backing corpus record, or ``None`` when absent.
        """
        if self.uri is None:
            return None
        model = self.pool.get(self.uri)
        return model if isinstance(model, corpus_records.Corpus) else None

    def split(self, name: str) -> Dataset[expression_records.Expression]:
        """Return the corpus member expressions assigned to a named split.

        Expressions are joined to their membership records by AT-URI and kept
        when a membership's ``split`` slug equals ``name`` (for example
        ``"train"``, ``"dev"``, ``"test"``, or ``"unlabeled"``). An expression
        with several memberships is included when any of them carries the split.

        Parameters
        ----------
        name : str
            The split slug to select.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of the expression models in that split, in pool order.
        """
        split_uris = {
            membership.expressionRef
            for membership in self._memberships()
            if membership.split == name
        }
        records = [
            model for uri, model in self._member_expressions() if uri in split_uris
        ]
        return Dataset(records, model=expression_records.Expression)

    def splits(self) -> tuple[str, ...]:
        """Return the distinct split slugs present in the corpus memberships.

        Returns
        -------
        tuple of str
            The split slugs, sorted, excluding memberships with no split.
        """
        names = {
            membership.split
            for membership in self._memberships()
            if membership.split is not None
        }
        return tuple(sorted(names))

    def add_membership(
        self,
        uri: str,
        membership: corpus_records.Membership,
    ) -> None:
        """Add a membership record to the corpus graph.

        Parameters
        ----------
        uri : str
            The AT-URI of the membership record.
        membership : pub.layers.corpus.Membership
            The membership record binding an expression to a corpus.
        """
        self.pool.add(uri, membership)

    # graph-aware joins --------------------------------------------------------

    def with_annotations(self) -> Dataset[ExpressionWithAnnotations]:
        """Join each expression to the annotation layers that target it.

        Annotation layers carry an ``expression`` AT-URI; this groups the layers
        by that ref and attaches them to the matching expression. Expressions
        with no layers still appear, with an empty group.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of expression-and-annotations join rows.
        """
        grouped: dict[str, list[annotation_records.AnnotationLayer]] = {}
        for _, model in self._models_of(_ANNOTATION_LAYER_NSID):
            if isinstance(model, annotation_records.AnnotationLayer):
                grouped.setdefault(model.expression, []).append(model)
        rows = [
            ExpressionWithAnnotations(
                expression=model,
                uri=uri,
                annotation_layers=tuple(grouped.get(uri, ())),
            )
            for uri, model in self._member_expressions()
        ]
        return Dataset(rows, model=ExpressionWithAnnotations)

    def with_media(self) -> Dataset[ExpressionWithMedia]:
        """Join each expression to the media record it references.

        An expression's ``mediaRef`` AT-URI is resolved through the pool; when
        the media record is not loaded the join row carries ``None``.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of expression-and-media join rows.
        """
        rows: list[ExpressionWithMedia] = []
        for uri, model in self._member_expressions():
            resolved: media_records.Media | None = None
            if model.mediaRef is not None:
                target = self.pool.resolve(model.mediaRef)
                if isinstance(target, media_records.Media):
                    resolved = target
            rows.append(
                ExpressionWithMedia(expression=model, uri=uri, media=resolved),
            )
        return Dataset(rows, model=ExpressionWithMedia)

    def with_segmentation(self) -> Dataset[ExpressionWithSegmentation]:
        """Join each expression to the segmentations that target it.

        Segmentations carry an ``expression`` AT-URI; this groups them by that
        ref and attaches them to the matching expression.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of expression-and-segmentation join rows.
        """
        grouped: dict[str, list[segmentation_records.Segmentation]] = {}
        for _, model in self._models_of(_SEGMENTATION_NSID):
            if isinstance(model, segmentation_records.Segmentation):
                grouped.setdefault(model.expression, []).append(model)
        rows = [
            ExpressionWithSegmentation(
                expression=model,
                uri=uri,
                segmentations=tuple(grouped.get(uri, ())),
            )
            for uri, model in self._member_expressions()
        ]
        return Dataset(rows, model=ExpressionWithSegmentation)

    # authoring ----------------------------------------------------------------

    def add_expression(
        self,
        uri: str,
        expression: expression_records.Expression,
    ) -> None:
        """Add an expression record to the corpus graph.

        Parameters
        ----------
        uri : str
            The AT-URI of the expression.
        expression : pub.layers.expression.Expression
            The expression record to add.
        """
        self.pool.add(uri, expression)

    def add_annotation_layer(
        self,
        uri: str,
        layer: annotation_records.AnnotationLayer,
    ) -> None:
        """Add an annotation layer record to the corpus graph.

        Parameters
        ----------
        uri : str
            The AT-URI of the annotation layer.
        layer : pub.layers.annotation.AnnotationLayer
            The annotation layer record to add.
        """
        self.pool.add(uri, layer)

    def add_record(self, uri: str, record: dx.Model) -> None:
        """Add any Layers record to the corpus graph by AT-URI.

        Parameters
        ----------
        uri : str
            The AT-URI of the record.
        record : didactic.api.Model
            The record to add (expression, layer, segmentation, media, etc.).
        """
        self.pool.add(uri, record)

    # persistence --------------------------------------------------------------

    def save_to_repo(self, path: Path) -> str:
        """Persist the corpus graph to a didactic Repository and commit.

        Delegates to the store's :class:`lairs.store.repository.Repository`,
        staging every record under its AT-URI and committing a single snapshot.

        Parameters
        ----------
        path : pathlib.Path
            The repository directory to initialise or reuse.

        Returns
        -------
        str
            The new commit revision identifier.
        """
        repo = Repository.init(path)
        for uri in self.pool.uris():
            model = self.pool.get(uri)
            if model is not None:
                repo.save(uri, model)
        return repo.commit("materialize corpus snapshot")

    def materialize(self, out_dir: Path) -> list[Path]:
        """Materialize the corpus to Parquet views.

        Builds the normalized ``expressions`` and ``annotations`` Arrow views
        from the graph and delegates writing to the store's Arrow
        :func:`lairs.store.arrow.materialize`. The expressions view holds the
        corpus member expressions only (see :attr:`expressions`).

        Parameters
        ----------
        out_dir : pathlib.Path
            The output directory for the views.

        Returns
        -------
        list of pathlib.Path
            The written view files, in name order.
        """
        expressions = [model for _, model in self._member_expressions()]
        layers = [
            (uri, model) for uri, model in self._models_of(_ANNOTATION_LAYER_NSID)
        ]
        views = {
            "expressions": expressions_table(expressions),
            "annotations": annotations_table(layers),
        }
        # materialize takes a repository for the default derive path, but it is
        # unused when explicit views are passed; a throwaway repo in a temporary
        # directory satisfies the signature without leaving a stray .repo inside
        # the caller's output directory.
        with tempfile.TemporaryDirectory(prefix="lairs-materialize-") as scratch:
            repo = Repository.init(Path(scratch) / "repo")
            return materialize(repo, out_dir, views=views)


def _decode_envelope(
    envelope: RecordEnvelope,
) -> tuple[str, dx.Model] | None:
    """Decode a record envelope into an AT-URI and model, by its collection.

    The envelope value is validated through ``model_validate_json`` rather than
    ``model_validate`` because a record fetched over XRPC carries datetimes (and
    other formatted scalars) as JSON strings, which the JSON validator coerces
    but the in-memory dict validator does not.

    Parameters
    ----------
    envelope : lairs.atproto.pds.RecordEnvelope
        The record envelope to decode.

    Returns
    -------
    tuple of (str, didactic.api.Model) or None
        The AT-URI and decoded model, or ``None`` when the collection is not a
        known Layers record type, the value is not a decodable object, or the
        value fails validation. A single undecodable record is skipped rather
        than aborting a whole-corpus load.
    """
    model_cls = _NSID_MODELS.get(_nsid_of(envelope.uri))
    if model_cls is None:
        return None
    if not isinstance(envelope.value, dict):
        return None
    try:
        serialized = json.dumps(normalize_blob_refs(envelope.value))
    except TypeError, ValueError:
        # a value carrying a non-JSON-serializable object is not a record this
        # loader can decode; skip it like a validation failure.
        return None
    try:
        model = model_cls.model_validate_json(serialized)
    except dx.ValidationError:
        return None
    return envelope.uri, model


def _authority_of(uri: str) -> str:
    """Return the authority (DID or handle) segment of an AT-URI.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The authority segment, or the empty string when absent.
    """
    body = uri.removeprefix("at://")
    return body.split("/", 1)[0] if body else ""


def _load_from_pds(
    uri: str,
    client: PdsClient,
) -> Corpus:
    """Load a corpus graph by enumerating an authority's collections via a PDS.

    Every Layers collection of the authority is read into the pool, including
    its membership records. The returned :class:`Corpus` carries ``uri``, so its
    expression views and joins are restricted to the expressions whose
    memberships reference this corpus; records belonging to other corpora hosted
    by the same authority remain in the pool but do not surface in the views.

    Parameters
    ----------
    uri : str
        The corpus AT-URI whose authority is enumerated.
    client : lairs.atproto.pds.PdsClient
        The PDS client to read through.

    Returns
    -------
    Corpus
        The loaded corpus graph, scoped to this corpus's members.
    """
    authority = _authority_of(uri)
    pool = ModelPool()
    for nsid in _NSID_MODELS:
        for envelope in client.list_records(authority, nsid):
            decoded = _decode_envelope(envelope)
            if decoded is not None:
                pool.add(decoded[0], decoded[1])
    return Corpus(pool, uri=uri)


def load_corpus(
    uri: str,
    *,
    source: str = "auto",
    cache_dir: str | None = None,
    revision: str | None = None,
    pds_client: PdsClient | None = None,
) -> Corpus:
    """Load a corpus by AT-URI from a PDS or the appview.

    The loader enumerates the Layers record collections of the AT-URI's
    authority and builds the joined graph. The corpus's expression views and
    joins are then scoped to the expressions reachable through membership records
    whose ``corpusRef`` matches ``uri``, so an authority that hosts several
    corpora yields only this corpus's members. The ``pds`` source reads directly
    from a PDS; ``appview`` and ``auto`` are not implemented without an appview
    client yet and currently require the ``pds`` source with an injected client.

    Parameters
    ----------
    uri : str
        The corpus AT-URI (its authority is enumerated).
    source : str, optional
        The source to load from (``"pds"``, ``"appview"``, or ``"auto"``).
    cache_dir : str or None, optional
        A local cache directory (reserved; not yet used).
    revision : str or None, optional
        A revision (Repository tag) to resolve (reserved; not yet used).
    pds_client : lairs.atproto.pds.PdsClient or None, optional
        An injected PDS client. Required for the ``pds`` source; supplying it
        avoids network setup in tests.

    Returns
    -------
    Corpus
        The loaded corpus.

    Raises
    ------
    ValueError
        When ``source`` is not a recognised source value.
    NotImplementedError
        When the appview source is requested without an appview client, or the
        PDS source is requested without an injected client.
    """
    if source not in _VALID_SOURCES:
        valid = sorted(_VALID_SOURCES)
        msg = f"unknown corpus source {source!r}; expected one of {valid}"
        raise ValueError(msg)
    _ = (cache_dir, revision)
    if source in {_SOURCE_PDS, _SOURCE_AUTO} and pds_client is not None:
        return _load_from_pds(uri, pds_client)
    if source == _SOURCE_APPVIEW:
        msg = "appview corpus loading requires an appview client; inject a pds_client"
        raise NotImplementedError(msg)
    msg = "corpus loading needs an injected pds_client until endpoint discovery lands"
    raise NotImplementedError(msg)
