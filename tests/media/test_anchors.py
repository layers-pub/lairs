"""Unit tests for lairs.media.anchors."""

from __future__ import annotations

import didactic.api as dx
import pytest

from lairs.media import anchors
from lairs.media.anchors import resolve_anchor
from lairs.media.audio import AudioBuffer
from lairs.media.neural import SignalBuffer
from lairs.media.video import VideoFrame
from lairs.records._generated.defs import (
    Anchor,
    BoundingBox,
    ExternalTarget,
    Keyframe,
    PageAnchor,
    Span,
    SpatioTemporalAnchor,
    TemporalSpan,
    TokenRef,
    TokenRefSequence,
    Uuid,
)


# structural stand-ins for the generated anchor variant models
class _TextSpan(dx.Model):
    byte_start: int = dx.field(description="start byte")
    byte_end: int = dx.field(description="end byte")


class _TokenRef(dx.Model):
    tokenization_id: str = dx.field(description="tokenization id")
    token_index: int = dx.field(description="token index")


class _TokenRefSequence(dx.Model):
    tokenization_id: str = dx.field(description="tokenization id")
    token_indexes: tuple[int, ...] = dx.field(description="token indexes")


class _TemporalSpan(dx.Model):
    start: int = dx.field(description="start ms")
    ending: int = dx.field(description="end ms")


class _Bbox(dx.Model):
    x: int = dx.field(description="x")
    y: int = dx.field(description="y")
    width: int = dx.field(description="width")
    height: int = dx.field(description="height")


class _KF(dx.Model):
    time_ms: int = dx.field(description="time")
    bbox: _Bbox = dx.field(description="box")


class _SpatioTemporal(dx.Model):
    keyframes: tuple[_KF, ...] = dx.field(description="keyframes")
    interpolation: str | None = dx.field(default="linear", description="mode")


class _Anchor(dx.Model):
    """A structural stand-in for the ``anchor`` wrapper object."""

    text_span: _TextSpan | None = dx.field(default=None, description="text span")
    token_ref: _TokenRef | None = dx.field(default=None, description="token ref")
    temporal_span: _TemporalSpan | None = dx.field(
        default=None, description="temporal span"
    )


def test_exports() -> None:
    assert set(anchors.__all__) == {"AnchorTarget", "resolve_anchor"}


def test_text_span_slices_utf8() -> None:
    assert resolve_anchor(_TextSpan(byte_start=0, byte_end=5), "hello world") == "hello"
    assert (
        resolve_anchor(_TextSpan(byte_start=6, byte_end=11), "hello world") == "world"
    )


def test_text_span_via_wrapper() -> None:
    anchor = _Anchor(text_span=_TextSpan(byte_start=6, byte_end=11))
    assert resolve_anchor(anchor, "hello world") == "world"


def test_text_span_requires_str_target() -> None:
    with pytest.raises(TypeError, match="str target"):
        resolve_anchor(_TextSpan(byte_start=0, byte_end=1), ("a",))


def test_token_ref_selects_one_token() -> None:
    tokens = ("the", "cat", "sat")
    assert resolve_anchor(_TokenRef(tokenization_id="x", token_index=1), tokens) == (
        "cat",
    )


def test_token_ref_sequence_selects_many() -> None:
    tokens = ("the", "cat", "sat")
    anchor = _TokenRefSequence(tokenization_id="x", token_indexes=(0, 2))
    assert resolve_anchor(anchor, tokens) == ("the", "sat")


def test_token_anchor_requires_tuple_target() -> None:
    with pytest.raises(TypeError, match="tuple-of-str"):
        resolve_anchor(_TokenRef(tokenization_id="x", token_index=0), "hello")


def test_temporal_span_slices_audio() -> None:
    buf = AudioBuffer(
        sample_rate=100, channels=1, samples=tuple(float(i) for i in range(10))
    )
    result = resolve_anchor(_TemporalSpan(start=0, ending=30), buf)
    assert isinstance(result, AudioBuffer)
    assert result.samples == (0.0, 1.0, 2.0)


def test_temporal_span_windows_signal() -> None:
    buf = SignalBuffer(
        sample_rate=100.0, channels=("a",), samples=((0.0, 1.0, 2.0, 3.0, 4.0),)
    )
    result = resolve_anchor(_TemporalSpan(start=0, ending=30), buf)
    assert isinstance(result, SignalBuffer)
    assert result.samples == ((0.0, 1.0, 2.0),)


def test_temporal_span_rejects_text_target() -> None:
    with pytest.raises(TypeError, match="AudioBuffer or SignalBuffer"):
        resolve_anchor(_TemporalSpan(start=0, ending=1), "abc")


def test_bounding_box_crops_frame() -> None:
    frame = VideoFrame(index=0, width=4, height=2, pixels=bytes(range(24)))
    cropped = resolve_anchor(_Bbox(x=0, y=0, width=2, height=1), frame)
    assert isinstance(cropped, VideoFrame)
    assert cropped.width == 2
    assert cropped.pixels == bytes(range(6))


def test_bounding_box_requires_frame_target() -> None:
    with pytest.raises(TypeError, match="VideoFrame target"):
        resolve_anchor(_Bbox(x=0, y=0, width=1, height=1), "abc")


def test_spatio_temporal_interpolates_to_frame() -> None:
    # the frame index stands in for its timestamp in milliseconds
    frame = VideoFrame(index=50, width=100, height=100, pixels=b"")
    anchor = _SpatioTemporal(
        keyframes=(
            _KF(time_ms=0, bbox=_Bbox(x=0, y=0, width=10, height=10)),
            _KF(time_ms=100, bbox=_Bbox(x=20, y=0, width=10, height=10)),
        ),
        interpolation="linear",
    )
    result = resolve_anchor(anchor, frame)
    assert isinstance(result, VideoFrame)
    # interpolated box at t=50 is x=10, w=10, h=10 -> a 10x10 crop
    assert result.width == 10
    assert result.height == 10


def test_spatio_temporal_requires_frame_target() -> None:
    anchor = _SpatioTemporal(
        keyframes=(_KF(time_ms=0, bbox=_Bbox(x=0, y=0, width=1, height=1)),)
    )
    with pytest.raises(TypeError, match="VideoFrame target"):
        resolve_anchor(anchor, "abc")


def test_unknown_anchor_kind_raises() -> None:
    class _Mystery(dx.Model):
        note: str = dx.field(description="nothing recognisable")

    with pytest.raises(ValueError, match="could not infer anchor kind"):
        resolve_anchor(_Mystery(note="?"), "abc")


# the following tests build real generated Anchor instances from
# lairs.records._generated.defs so the structural dispatch is exercised against
# the actual lexicon shapes, not hand-rolled stand-ins.


def test_real_text_span_via_wrapper() -> None:
    anchor = Anchor(textSpan=Span(byteStart=6, byteEnd=11))
    assert resolve_anchor(anchor, "hello world") == "world"


def test_real_token_ref_via_wrapper() -> None:
    anchor = Anchor(tokenRef=TokenRef(tokenIndex=1, tokenizationId=Uuid(value="x")))
    assert resolve_anchor(anchor, ("the", "cat", "sat")) == ("cat",)


def test_real_token_ref_sequence_via_wrapper() -> None:
    anchor = Anchor(
        tokenRefSequence=TokenRefSequence(
            tokenIndexes=(0, 2),
            tokenizationId=Uuid(value="x"),
        )
    )
    assert resolve_anchor(anchor, ("the", "cat", "sat")) == ("the", "sat")


def test_real_temporal_span_via_wrapper() -> None:
    anchor = Anchor(temporalSpan=TemporalSpan(start=0, ending=30))
    buf = AudioBuffer(
        sample_rate=100, channels=1, samples=tuple(float(i) for i in range(10))
    )
    result = resolve_anchor(anchor, buf)
    assert isinstance(result, AudioBuffer)
    assert result.samples == (0.0, 1.0, 2.0)


def test_real_page_anchor_resolves_nested_text_span() -> None:
    page = PageAnchor(page=2, textSpan=Span(byteStart=0, byteEnd=5))
    anchor = Anchor(pageAnchor=page)
    assert resolve_anchor(anchor, "hello world") == "hello"


def test_real_page_anchor_without_text_span_returns_page_text() -> None:
    anchor = Anchor(pageAnchor=PageAnchor(page=0))
    assert resolve_anchor(anchor, "page body") == "page body"


def test_real_external_target_resolves_to_source_uri() -> None:
    anchor = Anchor(externalTarget=ExternalTarget(source="https://example.com/doc"))
    assert resolve_anchor(anchor, "ignored") == "https://example.com/doc"


def test_real_spatio_temporal_uses_frame_time_not_index() -> None:
    anchor = Anchor(
        spatioTemporalAnchor=SpatioTemporalAnchor(
            temporalSpan=TemporalSpan(start=0, ending=100),
            keyframes=(
                Keyframe(timeMs=0, bbox=BoundingBox(x=0, y=0, width=10, height=10)),
                Keyframe(timeMs=100, bbox=BoundingBox(x=20, y=0, width=10, height=10)),
            ),
            interpolation="linear",
        )
    )
    # index and time_ms deliberately differ: resolution must use time_ms (50),
    # which interpolates to an in-bounds 10x10 crop. Using index (999) would
    # clamp to the last keyframe and crop at x=20.
    frame = VideoFrame(index=999, width=100, height=100, time_ms=50, pixels=b"")
    result = resolve_anchor(anchor, frame)
    assert isinstance(result, VideoFrame)
    assert result.width == 10
    assert result.height == 10


def test_real_spatio_temporal_clamps_to_temporal_span() -> None:
    anchor = Anchor(
        spatioTemporalAnchor=SpatioTemporalAnchor(
            temporalSpan=TemporalSpan(start=0, ending=40),
            keyframes=(
                Keyframe(timeMs=0, bbox=BoundingBox(x=0, y=0, width=10, height=10)),
                Keyframe(timeMs=100, bbox=BoundingBox(x=20, y=0, width=10, height=10)),
            ),
            interpolation="step",
        )
    )
    # a frame at time 80 is past the span's end (40); the query clamps to 40 and
    # step interpolation holds the left keyframe box (x=0).
    frame = VideoFrame(index=0, width=100, height=100, time_ms=80, pixels=b"")
    result = resolve_anchor(anchor, frame)
    assert isinstance(result, VideoFrame)
    assert result.width == 10


def test_real_spatio_temporal_honors_interpolation_uri() -> None:
    anchor = Anchor(
        spatioTemporalAnchor=SpatioTemporalAnchor(
            temporalSpan=TemporalSpan(start=0, ending=100),
            keyframes=(
                Keyframe(timeMs=0, bbox=BoundingBox(x=0, y=0, width=10, height=10)),
                Keyframe(timeMs=100, bbox=BoundingBox(x=20, y=0, width=10, height=10)),
            ),
            interpolationUri="at://did:plc:x/pub.layers.interpolation/step",
        )
    )
    # with no interpolation slug, the trailing path segment of interpolationUri
    # ("step") selects step interpolation, which holds the left keyframe at x=0.
    frame = VideoFrame(index=0, width=100, height=100, time_ms=50, pixels=b"")
    result = resolve_anchor(anchor, frame)
    assert isinstance(result, VideoFrame)
    # a step crop at the left keyframe is a 10x10 box anchored at x=0
    assert result.width == 10


def test_int_attr_excludes_bool() -> None:
    class _Flagged(dx.Model):
        token_index: bool = dx.field(description="a flag, not an index")

    # a bool field must not be read as an integer offset; with no real int field
    # the kind cannot be inferred.
    with pytest.raises(ValueError, match="could not infer anchor kind"):
        resolve_anchor(_Flagged(token_index=True), ("a", "b"))
