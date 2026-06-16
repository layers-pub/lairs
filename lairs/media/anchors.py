"""Unified anchor resolution over all anchor kinds.

``resolve_anchor`` dispatches over byte spans, token refs, temporal spans,
bounding boxes, and spatio-temporal anchors, returning the corresponding slice
or view of the right target (text, tokens, audio, video frame, or signal). It
is the single API the dataset layer calls for the data an annotation points
at.

The Layers ``anchor`` is an object whose optional variant fields select the
anchor kind (``textSpan``, ``tokenRef``, ``tokenRefSequence``, ``temporalSpan``,
``spatioTemporalAnchor`` and so on). Because the generated record models are not
required here, dispatch is structural: the wrapper's set variant is found and
the variant model's own fields are probed, tolerating both the camelCase
lexicon names and the snake_case generated names.
"""

from __future__ import annotations

import didactic.api as dx

from lairs.media.audio import AudioBuffer, slice_by_temporal
from lairs.media.neural import SignalBuffer, window_by_temporal
from lairs.media.video import (
    BoundingBox,
    Keyframe,
    VideoFrame,
    crop_to_bbox,
    interpolate_box,
)

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
    ("bounding_box", ("bounding_box", "boundingBox", "bbox")),
)


def _int_attr(model: dx.Model, *names: str) -> int | None:
    """Return the first present int-valued attribute among ``names``."""
    for name in names:
        value = getattr(model, name, None)
        if isinstance(value, int):
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
    """Infer the anchor kind from the fields a variant model carries."""
    if _int_attr(model, "byte_start", "byteStart") is not None:
        return "text_span"
    if getattr(model, "keyframes", None) is not None or _has(
        model, "spatio_temporal_anchor", "spatioTemporalAnchor"
    ):
        return "spatio_temporal"
    if _has(model, "token_indexes", "tokenIndexes"):
        return "token_ref_sequence"
    if _int_attr(model, "token_index", "tokenIndex") is not None:
        return "token_ref"
    if _int_attr(model, "start") is not None and _int_attr(model, "ending") is not None:
        return "temporal_span"
    if _int_attr(model, "width") is not None and _int_attr(model, "height") is not None:
        return "bounding_box"
    msg = "could not infer anchor kind from the supplied model"
    raise ValueError(msg)


def _has(model: dx.Model, *names: str) -> bool:
    """Return whether any of ``names`` is a present, non-None attribute."""
    return any(getattr(model, name, None) is not None for name in names)


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
        The resolved slice or view, dispatched on the anchor kind.

    Raises
    ------
    TypeError
        If the anchor kind does not match the supplied target type.
    ValueError
        If the anchor kind cannot be determined.
    """
    kind, variant = _unwrap(anchor)
    if kind == "text_span":
        return _resolve_text_span(variant, target)
    if kind in {"token_ref", "token_ref_sequence"}:
        return _resolve_token(kind, variant, target)
    if kind == "temporal_span":
        return _resolve_temporal(variant, target)
    if kind == "bounding_box":
        return _resolve_bbox(variant, target)
    return _resolve_spatio_temporal(variant, target)


def _resolve_text_span(variant: dx.Model, target: AnchorTarget) -> str:
    """Resolve a byte-span anchor to a UTF-8 text slice."""
    if not isinstance(target, str):
        msg = "text-span anchors require a str target"
        raise TypeError(msg)
    start = _int_attr(variant, "byte_start", "byteStart") or 0
    end = _int_attr(variant, "byte_end", "byteEnd") or 0
    return target.encode("utf-8")[start:end].decode("utf-8", errors="replace")


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
        index = _int_attr(variant, "token_index", "tokenIndex") or 0
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
    start = _int_attr(variant, "start", "start_ms", "startMs") or 0
    end = _int_attr(variant, "ending", "end_ms", "endMs") or 0
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
    box = BoundingBox(
        x=float(_int_attr(variant, "x") or 0),
        y=float(_int_attr(variant, "y") or 0),
        width=float(_int_attr(variant, "width") or 0),
        height=float(_int_attr(variant, "height") or 0),
    )
    return crop_to_bbox(target, box)


def _resolve_spatio_temporal(
    variant: dx.Model,
    target: AnchorTarget,
) -> BoundingBox | VideoFrame:
    """Resolve a spatio-temporal anchor to a per-frame box or a cropped frame.

    Keyframes are interpolated to the target frame's timestamp. With a plain
    frame target the interpolated box is returned; the same box can then be fed
    to :func:`lairs.media.video.crop_to_bbox`.
    """
    interpolation = getattr(variant, "interpolation", None) or "linear"
    if interpolation not in {"linear", "step", "cubic"}:
        interpolation = "linear"
    keyframes = _collect_keyframes(variant)
    if isinstance(target, VideoFrame):
        time_ms = target.index
        box = interpolate_box(keyframes, time_ms, interpolation)
        return crop_to_bbox(target, box)
    msg = "spatio-temporal anchors require a VideoFrame target"
    raise TypeError(msg)


def _collect_keyframes(variant: dx.Model) -> tuple[Keyframe, ...]:
    """Build interpolation keyframes from the variant's keyframe models."""
    raw = getattr(variant, "keyframes", None) or ()
    collected: list[Keyframe] = []
    for entry in raw:
        if not isinstance(entry, dx.Model):
            continue
        time_ms = _int_attr(entry, "time_ms", "timeMs") or 0
        bbox = getattr(entry, "bbox", None) or getattr(entry, "box", None)
        if isinstance(bbox, BoundingBox):
            box = bbox
        elif isinstance(bbox, dx.Model):
            box = BoundingBox(
                x=float(_int_attr(bbox, "x") or 0),
                y=float(_int_attr(bbox, "y") or 0),
                width=float(_int_attr(bbox, "width") or 0),
                height=float(_int_attr(bbox, "height") or 0),
            )
        else:
            box = BoundingBox(x=0.0, y=0.0, width=0.0, height=0.0)
        collected.append(Keyframe(time_ms=time_ms, box=box))
    return tuple(collected)
