"""Unit and integration tests for lairs.media.video."""

from __future__ import annotations

import io

import pytest

from lairs.media import video
from lairs.media.resolve import MediaHandle
from lairs.media.video import (
    BoundingBox,
    Keyframe,
    VideoFrame,
    crop_to_bbox,
    frame_at_ms,
    interpolate_box,
)


def test_exports() -> None:
    assert set(video.__all__) == {
        "BoundingBox",
        "Keyframe",
        "VideoFrame",
        "crop_to_bbox",
        "frame_at_ms",
        "interpolate_box",
    }


def test_video_frame_construction() -> None:
    frame = VideoFrame(index=0, width=640, height=480)
    assert frame.index == 0
    assert frame.width == 640
    assert frame.pixels == b""


def _keyframes() -> tuple[Keyframe, Keyframe]:
    return (
        Keyframe(time_ms=0, box=BoundingBox(x=0.0, y=0.0, width=10.0, height=10.0)),
        Keyframe(time_ms=100, box=BoundingBox(x=10.0, y=20.0, width=10.0, height=10.0)),
    )


def test_interpolate_linear() -> None:
    box = interpolate_box(_keyframes(), 50, "linear")
    assert box.x == 5.0
    assert box.y == 10.0


def test_interpolate_step_holds_left() -> None:
    box = interpolate_box(_keyframes(), 50, "step")
    assert box.x == 0.0
    assert box.y == 0.0


def test_interpolate_cubic_eases() -> None:
    # smoothstep at the midpoint equals the linear midpoint
    box = interpolate_box(_keyframes(), 50, "cubic")
    assert box.x == 5.0
    # but away from the midpoint it differs from linear
    cubic = interpolate_box(_keyframes(), 25, "cubic")
    linear = interpolate_box(_keyframes(), 25, "linear")
    assert cubic.x != linear.x


def test_interpolate_clamps_outside_range() -> None:
    keyframes = _keyframes()
    assert interpolate_box(keyframes, -10, "linear").x == 0.0
    assert interpolate_box(keyframes, 500, "linear").x == 10.0


def test_interpolate_requires_keyframes() -> None:
    with pytest.raises(ValueError, match="at least one keyframe"):
        interpolate_box((), 0, "linear")


def test_crop_to_bbox() -> None:
    # a 4x2 rgb frame: 24 bytes, row-major
    frame = VideoFrame(index=0, width=4, height=2, pixels=bytes(range(24)))
    cropped = crop_to_bbox(frame, BoundingBox(x=0.0, y=0.0, width=2.0, height=1.0))
    assert cropped.width == 2
    assert cropped.height == 1
    # top-left two pixels of row 0 are bytes 0..5
    assert cropped.pixels == bytes(range(6))


def test_crop_to_bbox_offset_region() -> None:
    frame = VideoFrame(index=0, width=4, height=2, pixels=bytes(range(24)))
    cropped = crop_to_bbox(frame, BoundingBox(x=2.0, y=1.0, width=2.0, height=1.0))
    assert cropped.width == 2
    assert cropped.height == 1
    # row 1 starts at byte 12, column 2 starts at +6
    assert cropped.pixels == bytes(range(18, 24))


def test_crop_to_bbox_rejects_out_of_bounds() -> None:
    frame = VideoFrame(index=0, width=4, height=2, pixels=bytes(range(24)))
    with pytest.raises(ValueError, match="outside the frame"):
        crop_to_bbox(frame, BoundingBox(x=0.0, y=0.0, width=10.0, height=10.0))


def test_crop_to_bbox_rejects_truncated_payload() -> None:
    # a 4x2 rgb24 frame needs 24 bytes; a 12-byte payload is truncated.
    frame = VideoFrame(index=0, width=4, height=2, pixels=bytes(range(12)))
    with pytest.raises(ValueError, match="pixel payload"):
        crop_to_bbox(frame, BoundingBox(x=0.0, y=0.0, width=2.0, height=1.0))


def test_crop_to_bbox_allows_empty_payload() -> None:
    # a metadata-only frame (no pixels) crops to dimensions without slicing.
    frame = VideoFrame(index=0, width=4, height=2)
    cropped = crop_to_bbox(frame, BoundingBox(x=0.0, y=0.0, width=2.0, height=1.0))
    assert cropped.width == 2
    assert cropped.height == 1
    assert cropped.pixels == b""


def test_frame_at_ms_rejects_empty_handle() -> None:
    handle = MediaHandle(cid="bafy", mime_type="video/mp4", modality="video")
    with pytest.raises(ValueError, match="no bytes to decode"):
        frame_at_ms(handle, 100)


def test_frame_at_ms_rejects_negative_time() -> None:
    handle = MediaHandle(cid="bafy", mime_type="video/mp4", modality="video", data=b"x")
    with pytest.raises(ValueError, match="non-negative"):
        frame_at_ms(handle, -1)


@pytest.mark.integration
def test_frame_at_ms_live() -> None:
    # synthesize a tiny three-frame mp4 in memory so the av decode path runs
    # without depending on an external fixture file.
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mp4") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width = 16
        stream.height = 16
        stream.pix_fmt = "yuv420p"
        for index in range(3):
            array = np.full((16, 16, 3), index * 60, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    handle = MediaHandle(
        cid="bafy",
        mime_type="video/mp4",
        modality="video",
        data=buffer.getvalue(),
    )
    decoded = frame_at_ms(handle, 0)
    assert decoded.index == 0
    assert decoded.width == 16
    assert decoded.height == 16
    # the frame carries a presentation time set during decode, distinct from
    # its ordinal index.
    assert decoded.time_ms >= 0
    # row-major rgb24 payload for a 16x16 frame.
    assert len(decoded.pixels) == 16 * 16 * 3


@pytest.mark.integration
def test_frame_at_ms_rejects_streamless_container() -> None:
    # an audio-only container has no video stream; decoding must raise a clear
    # error rather than an opaque IndexError.
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="wav") as out:
        stream = out.add_stream("pcm_s16le", rate=8000)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            np.zeros((1, 800), dtype=np.int16),
            format="s16",
            layout="mono",
        )
        frame.sample_rate = 8000
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    handle = MediaHandle(
        cid="bafy",
        mime_type="audio/wav",
        modality="audio",
        data=buffer.getvalue(),
    )
    with pytest.raises(ValueError, match="no video stream"):
        frame_at_ms(handle, 0)
