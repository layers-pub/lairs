"""Ergonomic anchor, layer, and record builders over the generated models.

These builders are behaviour over the generated models, not replacements for
them; authoring is validated against the lexicons by construction. The builders
add three conveniences over raw model construction.

Anchor builders (:func:`span`, :func:`token_ref`, :func:`temporal`,
:func:`bbox`, :func:`spatio_temporal`) construct the correct anchor sub-model
and wrap it in an :class:`~lairs.records.defs.Anchor` object. The Layers anchor
is an object with mutually-exclusive optional reference properties rather than a
formal tagged union, so each builder sets exactly one property.

Layer builders (:class:`LayerBuilder`) assemble an
:class:`~lairs.records.annotation.AnnotationLayer` and append annotations
without hand-writing UUIDs.

Cross-reference helpers (:class:`PendingId`, :func:`reference`) resolve a
reference target from a published model, a pending local identifier, or an
AT-URI string, so authoring works whether or not the target is published yet.

All builders validate construction-time arguments against the ``dx.field``
metadata carried by the generated models (``knownValues``, numeric ranges,
required-ness), raising a clear :class:`BuildError` rather than deferring to a
post-hoc PDS rejection. didactic does not enforce these lexicon constraints at
construction time, so the builders enforce them here.
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING, Self

from lairs.records._generated.annotation import Annotation, AnnotationLayer
from lairs.records._generated.defs import (
    Anchor,
    BoundingBox,
    Keyframe,
    Span,
    SpatioTemporalAnchor,
    TemporalSpan,
    TokenRef,
    Uuid,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    import didactic.api as dx

__all__ = [
    "BuildError",
    "LayerBuilder",
    "PendingId",
    "bbox",
    "keyframe",
    "new_uuid",
    "reference",
    "span",
    "spatio_temporal",
    "temporal",
    "token_ref",
]


class BuildError(ValueError):
    """Raised when a builder argument violates a lexicon constraint.

    Carries a construction-time message so authoring fails fast with a helpful
    diagnostic rather than at PDS-write time.
    """


def _check_minimum(model: type[dx.Model], field: str, value: int) -> None:
    """Validate an integer against a field's ``minimum`` extra.

    Parameters
    ----------
    model : type of didactic.api.Model
        The model whose field metadata is consulted.
    field : str
        The field name to read the ``minimum`` extra from.
    value : int
        The value to validate.

    Raises
    ------
    BuildError
        If the value is below the field's declared minimum.
    """
    extras = model.__field_specs__[field].extras
    minimum = extras.get("minimum")
    if isinstance(minimum, int) and value < minimum:
        msg = f"{model.__name__}.{field} must be >= {minimum}, got {value}"
        raise BuildError(msg)


def _check_maximum(model: type[dx.Model], field: str, value: int) -> None:
    """Validate an integer against a field's ``maximum`` extra.

    Parameters
    ----------
    model : type of didactic.api.Model
        The model whose field metadata is consulted.
    field : str
        The field name to read the ``maximum`` extra from.
    value : int
        The value to validate.

    Raises
    ------
    BuildError
        If the value is above the field's declared maximum.
    """
    extras = model.__field_specs__[field].extras
    maximum = extras.get("maximum")
    if isinstance(maximum, int) and value > maximum:
        msg = f"{model.__name__}.{field} must be <= {maximum}, got {value}"
        raise BuildError(msg)


def _check_known_value(model: type[dx.Model], field: str, value: str) -> None:
    """Warn-free validation of a string against a field's ``knownValues``.

    Layers enums are open (``knownValues``), so an unknown-but-valid value from
    the wild must not fail. This helper therefore only rejects an *empty*
    string for a field that declares known values; any non-empty value is
    accepted, matching the open-enum semantics.

    Parameters
    ----------
    model : type of didactic.api.Model
        The model whose field metadata is consulted.
    field : str
        The field name to read the ``knownValues`` extra from.
    value : str
        The value to validate.

    Raises
    ------
    BuildError
        If the field declares known values and the value is empty.
    """
    extras = model.__field_specs__[field].extras
    known = extras.get("knownValues")
    if isinstance(known, tuple | list) and value == "":
        known_tuple = tuple(str(item) for item in known)
        msg = (
            f"{model.__name__}.{field} expects one of {known_tuple} "
            f"(or another community value), got an empty string"
        )
        raise BuildError(msg)


def new_uuid() -> Uuid:
    """Mint a fresh annotation UUID.

    Returns
    -------
    lairs.records.defs.Uuid
        A UUID value model wrapping a random version-4 UUID string.
    """
    return Uuid(value=str(_uuid.uuid4()))


# anchor builders ----------------------------------------------------------


def span(byte_start: int, byte_end: int) -> Anchor:
    """Build a byte-span anchor.

    Parameters
    ----------
    byte_start : int
        The UTF-8 byte start offset (0-indexed, inclusive).
    byte_end : int
        The UTF-8 byte end offset (exclusive).

    Returns
    -------
    lairs.records.defs.Anchor
        An anchor whose ``textSpan`` property carries the span.

    Raises
    ------
    BuildError
        If an offset is negative or the span is not well ordered.
    """
    _check_minimum(Span, "byteStart", byte_start)
    _check_minimum(Span, "byteEnd", byte_end)
    if byte_end < byte_start:
        msg = f"span byte_end ({byte_end}) must be >= byte_start ({byte_start})"
        raise BuildError(msg)
    return Anchor(textSpan=Span(byteStart=byte_start, byteEnd=byte_end))


def token_ref(tokenization_id: str, token_index: int) -> Anchor:
    """Build a token-reference anchor.

    Parameters
    ----------
    tokenization_id : str
        The tokenization UUID the index refers into.
    token_index : int
        The zero-based token index.

    Returns
    -------
    lairs.records.defs.Anchor
        An anchor whose ``tokenRef`` property carries the reference.

    Raises
    ------
    BuildError
        If the token index is negative or the tokenization id is empty.
    """
    if tokenization_id == "":
        msg = "token_ref tokenization_id must be a non-empty UUID string"
        raise BuildError(msg)
    _check_minimum(TokenRef, "tokenIndex", token_index)
    return Anchor(
        tokenRef=TokenRef(
            tokenIndex=token_index,
            tokenizationId=Uuid(value=tokenization_id),
        ),
    )


def temporal(start_ms: int, end_ms: int) -> Anchor:
    """Build a temporal-span anchor.

    Parameters
    ----------
    start_ms : int
        The start offset in milliseconds.
    end_ms : int
        The end offset in milliseconds.

    Returns
    -------
    lairs.records.defs.Anchor
        An anchor whose ``temporalSpan`` property carries the span.

    Raises
    ------
    BuildError
        If a time is negative or the span is not well ordered.
    """
    _check_minimum(TemporalSpan, "start", start_ms)
    _check_minimum(TemporalSpan, "ending", end_ms)
    if end_ms < start_ms:
        msg = f"temporal end_ms ({end_ms}) must be >= start_ms ({start_ms})"
        raise BuildError(msg)
    return Anchor(temporalSpan=TemporalSpan(start=start_ms, ending=end_ms))


def bbox(x: int, y: int, width: int, height: int) -> BoundingBox:
    """Build a bounding box.

    The bounding box is a standalone spatial value: it is used inside a
    keyframe (see :func:`keyframe`) or wherever a model embeds a
    :class:`~lairs.records.defs.BoundingBox`. The generated model uses integer
    pixel coordinates with ``width``/``height`` of at least one pixel.

    Parameters
    ----------
    x : int
        The x coordinate of the top-left corner in pixels.
    y : int
        The y coordinate of the top-left corner in pixels.
    width : int
        The box width in pixels (at least one).
    height : int
        The box height in pixels (at least one).

    Returns
    -------
    lairs.records.defs.BoundingBox
        The bounding box value model.

    Raises
    ------
    BuildError
        If the width or height is below the declared minimum.
    """
    _check_minimum(BoundingBox, "width", width)
    _check_minimum(BoundingBox, "height", height)
    return BoundingBox(x=x, y=y, width=width, height=height)


def keyframe(time_ms: int, box: BoundingBox) -> Keyframe:
    """Build a spatio-temporal keyframe.

    Parameters
    ----------
    time_ms : int
        The keyframe time in milliseconds.
    box : lairs.records.defs.BoundingBox
        The bounding box at this time (see :func:`bbox`).

    Returns
    -------
    lairs.records.defs.Keyframe
        The keyframe value model.

    Raises
    ------
    BuildError
        If the keyframe time is negative.
    """
    _check_minimum(Keyframe, "timeMs", time_ms)
    return Keyframe(timeMs=time_ms, bbox=box)


def spatio_temporal(
    temporal_span: TemporalSpan,
    keyframes: Sequence[Keyframe],
    interpolation: str = "linear",
) -> Anchor:
    """Build a spatio-temporal anchor.

    Parameters
    ----------
    temporal_span : lairs.records.defs.TemporalSpan
        The temporal span the keyframes range over.
    keyframes : collections.abc.Sequence of lairs.records.defs.Keyframe
        The keyframe boxes (see :func:`keyframe`).
    interpolation : str, optional
        The interpolation mode (``linear``, ``step``, or ``cubic``; an open
        vocabulary). Defaults to ``linear``.

    Returns
    -------
    lairs.records.defs.Anchor
        An anchor whose ``spatioTemporalAnchor`` property carries the value.

    Raises
    ------
    BuildError
        If no keyframes are supplied or the interpolation mode is empty.
    """
    if len(keyframes) == 0:
        msg = "spatio_temporal requires at least one keyframe"
        raise BuildError(msg)
    _check_known_value(SpatioTemporalAnchor, "interpolation", interpolation)
    anchor_value = SpatioTemporalAnchor(
        temporalSpan=temporal_span,
        keyframes=tuple(keyframes),
        interpolation=interpolation,
    )
    return Anchor(spatioTemporalAnchor=anchor_value)


# cross-reference helpers --------------------------------------------------


class PendingId(str):
    """A placeholder for a record not yet published to a PDS.

    Authoring frequently references a record (an expression, a media record,
    an ontology) before it has an AT-URI, because the whole graph is published
    as one batch. A :class:`PendingId` carries a stable local identifier that
    the publish path resolves to a real AT-URI once the referenced record
    commits. It subclasses :class:`str` so it can be carried in the same
    AT-URI-typed string fields and still be recognised by the publisher.

    Attributes
    ----------
    local_id : str
        A stable local identifier, unique within an authoring session.
    """

    __slots__ = ()

    def __new__(cls, local_id: str) -> Self:
        """Construct a pending-id placeholder.

        Parameters
        ----------
        local_id : str
            A stable local identifier, unique within an authoring session.

        Returns
        -------
        Self
            The placeholder string.
        """
        return super().__new__(cls, local_id)


def reference(target: dx.Model | PendingId | str, *, uri_field: str = "uri") -> str:
    """Resolve a cross-reference target to a reference string.

    The target may be a published model carrying its AT-URI in a field, a
    :class:`PendingId` placeholder, or an AT-URI string. A model is consulted
    for ``uri_field`` and falls back to a ``uri`` attribute; if neither is set,
    the model is not yet published and the caller should pass a
    :class:`PendingId` instead.

    Parameters
    ----------
    target : didactic.api.Model or PendingId or str
        The reference target.
    uri_field : str, optional
        The model field that holds the AT-URI, when ``target`` is a model.

    Returns
    -------
    str
        An AT-URI or a pending local id, suitable for an AT-URI-typed field.

    Raises
    ------
    BuildError
        If a model target carries no resolvable AT-URI.
    """
    if isinstance(target, PendingId):
        return str(target)
    if isinstance(target, str):
        return target
    value = getattr(target, uri_field, None)
    if not isinstance(value, str) or value == "":
        msg = (
            f"reference target {type(target).__name__} has no '{uri_field}' "
            f"AT-URI; pass a PendingId for an unpublished target"
        )
        raise BuildError(msg)
    return value


# layer builders -----------------------------------------------------------


class LayerBuilder:
    """An ergonomic assembler for an annotation layer.

    Collects annotations (auto-minting a UUID for each one that lacks it) and
    finalises them into a single
    :class:`~lairs.records.annotation.AnnotationLayer`, validating the layer's
    ``kind`` against the generated model's open vocabulary.

    Parameters
    ----------
    expression : str
        The AT-URI (or :class:`PendingId`) of the expression this layer
        annotates.
    kind : str
        The layer kind (``token-tag``, ``span``, ``relation``, ``tree``,
        ``graph``, ``tier``, or ``document-tag``; an open vocabulary).
    created_at : datetime.datetime
        The layer creation timestamp.
    subkind : str or None, optional
        The layer subkind, when applicable.
    formalism : str or None, optional
        The linguistic formalism or annotation standard, when applicable.
    tokenization_id : str or None, optional
        For token-aligned layers, the tokenization UUID these annotations align
        to.
    """

    def __init__(  # noqa: PLR0913  (an annotation layer carries these facets)
        self,
        expression: str,
        kind: str,
        created_at: datetime,
        *,
        subkind: str | None = None,
        formalism: str | None = None,
        tokenization_id: str | None = None,
    ) -> None:
        _check_known_value(AnnotationLayer, "kind", kind)
        if subkind is not None:
            _check_known_value(AnnotationLayer, "subkind", subkind)
        if formalism is not None:
            _check_known_value(AnnotationLayer, "formalism", formalism)
        self._expression = expression
        self._kind = kind
        self._created_at = created_at
        self._subkind = subkind
        self._formalism = formalism
        self._tokenization_id = tokenization_id
        self._annotations: list[Annotation] = []

    def add(
        self,
        *,
        anchor: Anchor | None = None,
        label: str | None = None,
        token_index: int | None = None,
        confidence: int | None = None,
        annotation_uuid: Uuid | None = None,
    ) -> Annotation:
        """Append an annotation, minting a UUID if none is supplied.

        Parameters
        ----------
        anchor : lairs.records.defs.Anchor or None, optional
            How this annotation attaches to the source data.
        label : str or None, optional
            The primary label (POS tag, entity type, relation, etc.).
        token_index : int or None, optional
            For token-level annotations, the 0-based token index.
        confidence : int or None, optional
            A confidence score scaled 0-1000, validated against the model range.
        annotation_uuid : lairs.records.defs.Uuid or None, optional
            An explicit UUID; a fresh one is minted when omitted.

        Returns
        -------
        lairs.records.annotation.Annotation
            The appended annotation.

        Raises
        ------
        BuildError
            If the token index is negative or the confidence is out of range.
        """
        if token_index is not None:
            _check_minimum(Annotation, "tokenIndex", token_index)
        if confidence is not None:
            _check_minimum(Annotation, "confidence", confidence)
            _check_maximum(Annotation, "confidence", confidence)
        annotation = Annotation(
            uuid=annotation_uuid if annotation_uuid is not None else new_uuid(),
            anchor=anchor,
            label=label,
            tokenIndex=token_index,
            confidence=confidence,
        )
        self._annotations.append(annotation)
        return annotation

    def build(self) -> AnnotationLayer:
        """Finalise the collected annotations into an annotation layer.

        Returns
        -------
        lairs.records.annotation.AnnotationLayer
            The assembled annotation layer.

        Raises
        ------
        BuildError
            If no annotations were added.
        """
        if len(self._annotations) == 0:
            msg = "an annotation layer must have at least one annotation"
            raise BuildError(msg)
        tokenization = (
            Uuid(value=self._tokenization_id)
            if self._tokenization_id is not None
            else None
        )
        return AnnotationLayer(
            expression=self._expression,
            kind=self._kind,
            createdAt=self._created_at,
            annotations=tuple(self._annotations),
            subkind=self._subkind,
            formalism=self._formalism,
            tokenizationId=tokenization,
        )
