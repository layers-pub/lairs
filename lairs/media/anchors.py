"""Unified anchor resolution over all anchor kinds.

``resolve_anchor`` dispatches over byte spans, token refs, temporal spans,
page anchors, external targets, bounding boxes, and spatio-temporal anchors,
returning the corresponding slice or view of the right target (text, tokens,
audio, video frame, or signal). It is the single API the dataset layer calls
for the data an annotation points at.

The Layers ``anchor`` is an object whose optional variant fields select the
anchor kind. The generated ``Anchor`` model carries seven variants
(``externalTarget``, ``pageAnchor``, ``spatioTemporalAnchor``, ``temporalSpan``,
``textSpan``, ``tokenRef``, ``tokenRefSequence``); every one is dispatched here.
Because the generated record models are not required, dispatch is structural:
the wrapper's set variant is found and the variant model's own fields are
probed, tolerating both the camelCase lexicon names and the snake_case
generated names.

A bounding box (``BoundingBox``) is never a top-level ``Anchor`` variant: it
only appears nested inside ``pageAnchor`` and inside the keyframes of
``spatioTemporalAnchor``. ``resolve_anchor`` therefore reaches a bounding box
through those variants, but also accepts a bare bounding-box model directly so
callers holding one can crop with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.media.audio import AudioBuffer, slice_by_temporal
from lairs.media.neural import SignalBuffer, window_by_temporal
from lairs.media.video import (
    BoundingBox,
    Interpolation,
    Keyframe,
    VideoFrame,
    crop_to_bbox,
    interpolate_box,
)

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["AnchorTarget", "resolve_anchor"]

type AnchorTarget = (
    str | tuple[str, ...] | AudioBuffer | SignalBuffer | VideoFrame | BoundingBox
)
"""The kinds of slice an anchor can resolve to across the supported targets."""

# the variant fields of the anchor object, mapped to a stable kind token
_VARIANT_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("text_span", ("text_span", "textSpan")),
    ("token_ref", ("token_ref", "tokenRef")),
    ("token_ref_sequence", ("token_ref_sequence", "tokenRefSequence")),
    ("temporal_span", ("temporal_span", "temporalSpan")),
    ("spatio_temporal", ("spatio_temporal_anchor", "spatioTemporalAnchor")),
    ("page", ("page_anchor", "pageAnchor")),
    ("external_target", ("external_target", "externalTarget")),
)

# interpolation slugs the keyframe interpolator understands, mapped to their
# literal mode so resolution preserves the precise Interpolation type
_INTERPOLATION_MODES: dict[str, Interpolation] = {
    "linear": "linear",
    "step": "step",
    "cubic": "cubic",
}


def _int_attr(model: dx.Model, *names: str) -> int | None:
    """Return the first present int-valued attribute among ``names``."""
    for name in names:
        value = getattr(model, name, None)
        # bool is an int subclass; exclude it so flags never read as offsets
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _unwrap(anchor: dx.Model) -> tuple[str, dx.Model]:
    """Return the anchor kind and the variant model an anchor selects.

    If ``anchor`` is the ``anchor`` wrapper object, the single set variant field
    is found; otherwise the anchor is treated as a variant model directly and
    its kind is inferred from the fields it carries.
    """
    for kind, names in _VARIANT_FIELDS:
        for name in names:
            value = getattr(anchor, name, None)
            if isinstance(value, dx.Model):
                return kind, value
    return _infer_kind(anchor), anchor


def _infer_kind(model: dx.Model) -> str:
    """Infer the anchor kind from the fields a variant model carries.

    The probes are ordered so that the most distinguishing field wins: an
    external target is identified by its ``source`` URI, a text span by its byte
    offsets, a spatio-temporal anchor by its keyframes, and so on. The two
    composite kinds (temporal span, bounding box) require both of their fields so
    they do not shadow a more specific variant.
    """
    for predicate, kind in _KIND_PROBES:
        if predicate(model):
            return kind
    msg = "could not infer anchor kind from the supplied model"
    raise ValueError(msg)


def _str_attr(model: dx.Model, *names: str) -> str | None:
    """Return the first present str-valued attribute among ``names``."""
    for name in names:
        value = getattr(model, name, None)
        if isinstance(value, str):
            return value
    return None


def _has(model: dx.Model, *names: str) -> bool:
    """Return whether any of ``names`` is a present, non-None attribute."""
    return any(getattr(model, name, None) is not None for name in names)


# ordered (predicate, kind) probes used to infer the kind of a bare variant
# model (one that is not wrapped in the anchor object). The order matters: the
# most distinguishing field is tested first so a specific variant is not
# shadowed by a composite one.
_KIND_PROBES: tuple[tuple[Callable[[dx.Model], bool], str], ...] = (
    (lambda m: _str_attr(m, "source") is not None, "external_target"),
    (lambda m: _int_attr(m, "byte_start", "byteStart") is not None, "text_span"),
    (
        lambda m: (
            getattr(m, "keyframes", None) is not None
            or _has(m, "spatio_temporal_anchor", "spatioTemporalAnchor")
        ),
        "spatio_temporal",
    ),
    (lambda m: _has(m, "token_indexes", "tokenIndexes"), "token_ref_sequence"),
    (lambda m: _int_attr(m, "token_index", "tokenIndex") is not None, "token_ref"),
    (
        lambda m: (
            _int_attr(m, "start") is not None and _int_attr(m, "ending") is not None
        ),
        "temporal_span",
    ),
    (lambda m: _int_attr(m, "page") is not None, "page"),
    (
        lambda m: (
            _int_attr(m, "width") is not None and _int_attr(m, "height") is not None
        ),
        "bounding_box",
    ),
)


def resolve_anchor(anchor: dx.Model, target: AnchorTarget) -> AnchorTarget:
    """Resolve an anchor to the slice of the target it points at.

    Parameters
    ----------
    anchor : didactic.Model
        An ``anchor`` wrapper or one of its variant models.
    target : AnchorTarget
        The data the anchor selects into: expression text (``str``), a token
        sequence (``tuple`` of ``str``), an ``AudioBuffer``, a ``SignalBuffer``,
        or a ``VideoFrame``.

    Returns
    -------
    AnchorTarget
        The resolved slice or view, dispatched on the anchor kind. An
        ``externalTarget`` anchor resolves to its source URI string, since the
        referenced bytes live outside the expression this layer can reach.

    Raises
    ------
    TypeError
        If the anchor kind does not match the supplied target type.
    ValueError
        If the anchor kind cannot be determined.
    """
    kind, variant = _unwrap(anchor)
    return _DISPATCH[kind](kind, variant, target)


def _resolve_text_span(variant: dx.Model, target: AnchorTarget) -> str:
    """Resolve a byte-span anchor to a UTF-8 text slice."""
    if not isinstance(target, str):
        msg = "text-span anchors require a str target"
        raise TypeError(msg)
    start = _coalesce_int(_int_attr(variant, "byte_start", "byteStart"))
    end = _coalesce_int(_int_attr(variant, "byte_end", "byteEnd"))
    return target.encode("utf-8")[start:end].decode("utf-8", errors="replace")


def _coalesce_int(value: int | None) -> int:
    """Return ``value`` or 0 when absent, preserving a legitimate zero."""
    return 0 if value is None else value


def _resolve_page(variant: dx.Model, target: AnchorTarget) -> str:
    """Resolve a page anchor to the page's text slice.

    A page anchor carries a 0-indexed page number plus an optional ``textSpan``
    (byte offsets into the page text) and an optional ``boundingBox``. When a
    text span is present and the target is the page text, the byte slice is
    returned; otherwise the whole page text is returned unchanged.
    """
    text_span = getattr(variant, "text_span", None) or getattr(
        variant, "textSpan", None
    )
    if isinstance(text_span, dx.Model):
        return _resolve_text_span(text_span, target)
    if not isinstance(target, str):
        msg = "page anchors without a textSpan require a str target"
        raise TypeError(msg)
    return target


def _resolve_external_target(variant: dx.Model) -> str:
    """Resolve an external-target anchor to its source URI.

    The bytes an ``externalTarget`` points at live outside the expression text
    and tokens this layer resolves against (a web page, a remote document), so
    the source URI is returned as an opaque identifier; fetching the resource is
    the caller's responsibility.
    """
    source = _str_attr(variant, "source")
    if source is None:
        msg = "external-target anchor carries no source URI"
        raise ValueError(msg)
    return source


def _resolve_token(
    kind: str,
    variant: dx.Model,
    target: AnchorTarget,
) -> tuple[str, ...]:
    """Resolve a token-ref (or sequence) anchor to the referenced tokens."""
    if not isinstance(target, tuple) or any(not isinstance(t, str) for t in target):
        msg = "token anchors require a tuple-of-str target"
        raise TypeError(msg)
    if kind == "token_ref":
        index = _coalesce_int(_int_attr(variant, "token_index", "tokenIndex"))
        return (target[index],)
    indexes = getattr(variant, "token_indexes", None) or getattr(
        variant, "tokenIndexes", None
    )
    if indexes is None:
        return ()
    return tuple(target[i] for i in indexes)


def _resolve_temporal(
    variant: dx.Model,
    target: AnchorTarget,
) -> AudioBuffer | SignalBuffer:
    """Resolve a temporal-span anchor to an audio or signal window."""
    start = _coalesce_int(_int_attr(variant, "start", "start_ms", "startMs"))
    end = _coalesce_int(_int_attr(variant, "ending", "end_ms", "endMs"))
    if isinstance(target, AudioBuffer):
        return slice_by_temporal(target, start, end)
    if isinstance(target, SignalBuffer):
        return window_by_temporal(target, start, end)
    msg = "temporal-span anchors require an AudioBuffer or SignalBuffer target"
    raise TypeError(msg)


def _resolve_bbox(variant: dx.Model, target: AnchorTarget) -> VideoFrame:
    """Resolve a bounding-box anchor to a cropped video frame."""
    if not isinstance(target, VideoFrame):
        msg = "bounding-box anchors require a VideoFrame target"
        raise TypeError(msg)
    return crop_to_bbox(target, _bbox_from_model(variant))


def _bbox_from_model(model: dx.Model) -> BoundingBox:
    """Build a video bounding box from a probed x/y/width/height model."""
    return BoundingBox(
        x=float(_coalesce_int(_int_attr(model, "x"))),
        y=float(_coalesce_int(_int_attr(model, "y"))),
        width=float(_coalesce_int(_int_attr(model, "width"))),
        height=float(_coalesce_int(_int_attr(model, "height"))),
    )


def _resolve_spatio_temporal(
    variant: dx.Model,
    target: AnchorTarget,
) -> BoundingBox | VideoFrame:
    """Resolve a spatio-temporal anchor to a cropped frame.

    Keyframes are interpolated against the target frame's presentation time
    (:attr:`lairs.media.video.VideoFrame.time_ms`, set during decode), not its
    ordinal index. The query time is clamped to the anchor's required
    ``temporalSpan`` so a frame outside the anchored window resolves to the
    nearest in-window keyframe box. The interpolated box then crops the frame
    through :func:`lairs.media.video.crop_to_bbox`.
    """
    interpolation = _resolve_interpolation(variant)
    keyframes = _collect_keyframes(variant)
    if not isinstance(target, VideoFrame):
        msg = "spatio-temporal anchors require a VideoFrame target"
        raise TypeError(msg)
    time_ms = _clamp_to_span(target.time_ms, variant)
    box = interpolate_box(keyframes, time_ms, interpolation)
    return crop_to_bbox(target, box)


def _resolve_interpolation(variant: dx.Model) -> Interpolation:
    """Resolve the interpolation mode, honoring ``interpolationUri`` as well.

    The lexicon treats ``interpolationUri`` as the primary selector and the
    ``interpolation`` slug as the fallback. The known interpolation-node URIs end
    in their slug, so the trailing path segment of ``interpolationUri`` is mapped
    to a known mode when present; otherwise the explicit slug is used. Anything
    unrecognized falls back to ``linear``.
    """
    slug = _str_attr(variant, "interpolation")
    if slug is not None and slug in _INTERPOLATION_MODES:
        return _INTERPOLATION_MODES[slug]
    uri = _str_attr(variant, "interpolation_uri", "interpolationUri")
    if uri:
        tail = uri.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1].lower()
        if tail in _INTERPOLATION_MODES:
            return _INTERPOLATION_MODES[tail]
    return "linear"


def _clamp_to_span(time_ms: int, variant: dx.Model) -> int:
    """Clamp a query time to the anchor's required temporal span, if present."""
    span = getattr(variant, "temporal_span", None) or getattr(
        variant, "temporalSpan", None
    )
    if not isinstance(span, dx.Model):
        return time_ms
    start = _int_attr(span, "start", "start_ms", "startMs")
    end = _int_attr(span, "ending", "end_ms", "endMs")
    if start is not None and time_ms < start:
        return start
    if end is not None and time_ms > end:
        return end
    return time_ms


def _collect_keyframes(variant: dx.Model) -> tuple[Keyframe, ...]:
    """Build interpolation keyframes from the variant's keyframe models."""
    raw = getattr(variant, "keyframes", None) or ()
    collected: list[Keyframe] = []
    for entry in raw:
        if not isinstance(entry, dx.Model):
            continue
        time_ms = _coalesce_int(_int_attr(entry, "time_ms", "timeMs"))
        bbox = getattr(entry, "bbox", None) or getattr(entry, "box", None)
        if isinstance(bbox, BoundingBox):
            box = bbox
        elif isinstance(bbox, dx.Model):
            box = _bbox_from_model(bbox)
        else:
            box = BoundingBox(x=0.0, y=0.0, width=0.0, height=0.0)
        collected.append(Keyframe(time_ms=time_ms, box=box))
    return tuple(collected)


# kind -> handler, every handler sharing the (kind, variant, target) signature
# so resolve_anchor dispatches with a single table lookup rather than a long
# return chain. Defined after the handlers it references.
_DISPATCH: dict[str, Callable[[str, dx.Model, AnchorTarget], AnchorTarget]] = {
    "text_span": lambda _k, v, t: _resolve_text_span(v, t),
    "token_ref": _resolve_token,
    "token_ref_sequence": _resolve_token,
    "temporal_span": lambda _k, v, t: _resolve_temporal(v, t),
    "page": lambda _k, v, t: _resolve_page(v, t),
    "external_target": lambda _k, v, _t: _resolve_external_target(v),
    "bounding_box": lambda _k, v, t: _resolve_bbox(v, t),
    "spatio_temporal": lambda _k, v, t: _resolve_spatio_temporal(v, t),
}
