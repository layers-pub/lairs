"""Video decoding, frame access, and bounding-box cropping.

Decodes video frames by time or index, crops frames to bounding boxes, and
resolves spatio-temporal anchors to dense per-frame boxes through keyframe
interpolation. Frames are didactic models carrying pixels in an opaque field.
The decode path requires the ``lairs[video]`` extra (``av``) at runtime, but
the keyframe-interpolation and box math are pure Python and need no extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.media.resolve import MediaHandle

__all__ = [
    "BoundingBox",
    "Keyframe",
    "VideoFrame",
    "crop_to_bbox",
    "frame_at_ms",
    "interpolate_box",
]

type Interpolation = Literal["linear", "step", "cubic"]
"""The supported keyframe interpolation modes."""


class BoundingBox(dx.Model):
    """An axis-aligned bounding box in pixel coordinates.

    Parameters
    ----------
    x : float
        The left coordinate in pixels.
    y : float
        The top coordinate in pixels.
    width : float
        The box width in pixels.
    height : float
        The box height in pixels.
    """

    x: float = dx.field(description="left coordinate in pixels")
    y: float = dx.field(description="top coordinate in pixels")
    width: float = dx.field(description="box width in pixels")
    height: float = dx.field(description="box height in pixels")


class Keyframe(dx.Model):
    """A timed bounding box used as a spatio-temporal keyframe.

    Parameters
    ----------
    time_ms : int
        The keyframe time in milliseconds.
    box : BoundingBox
        The bounding box at this time.
    """

    time_ms: int = dx.field(description="keyframe time in milliseconds")
    box: BoundingBox = dx.field(description="bounding box at this time")


class VideoFrame(dx.Model):
    """A single decoded video frame.

    Parameters
    ----------
    index : int
        The frame index.
    width : int
        The frame width in pixels.
    height : int
        The frame height in pixels.
    pixels : bytes, optional
        The frame pixels, carried as an opaque payload.
    """

    index: int = dx.field(description="frame index")
    width: int = dx.field(description="frame width in pixels")
    height: int = dx.field(description="frame height in pixels")
    pixels: bytes = dx.field(
        default=b"",
        opaque=True,
        description="frame pixels carried as an opaque payload",
    )


def _lerp(start: float, end: float, fraction: float) -> float:
    """Linearly interpolate between two scalars."""
    return start + (end - start) * fraction


def _cubic(start: float, end: float, fraction: float) -> float:
    """Smoothstep (cubic ease) interpolation between two scalars."""
    eased = fraction * fraction * (3.0 - 2.0 * fraction)
    return start + (end - start) * eased


def interpolate_box(
    keyframes: Sequence[Keyframe],
    time_ms: int,
    interpolation: Interpolation = "linear",
) -> BoundingBox:
    """Resolve the bounding box at a time by interpolating keyframes.

    Keyframes are assumed to be ordered by ``time_ms``. Times before the first
    or after the last keyframe clamp to the nearest keyframe box.

    Parameters
    ----------
    keyframes : sequence of Keyframe
        The ordered keyframes to interpolate between.
    time_ms : int
        The query time in milliseconds.
    interpolation : {"linear", "step", "cubic"}, optional
        The interpolation mode between adjacent keyframes.

    Returns
    -------
    BoundingBox
        The interpolated bounding box at ``time_ms``.

    Raises
    ------
    ValueError
        If ``keyframes`` is empty.
    """
    if not keyframes:
        msg = "interpolate_box requires at least one keyframe"
        raise ValueError(msg)
    if time_ms <= keyframes[0].time_ms:
        return keyframes[0].box
    if time_ms >= keyframes[-1].time_ms:
        return keyframes[-1].box
    left = keyframes[0]
    right = keyframes[-1]
    for index in range(len(keyframes) - 1):
        if keyframes[index].time_ms <= time_ms <= keyframes[index + 1].time_ms:
            left = keyframes[index]
            right = keyframes[index + 1]
            break
    if interpolation == "step":
        return left.box
    span = right.time_ms - left.time_ms
    fraction = 0.0 if span == 0 else (time_ms - left.time_ms) / span
    ease = _cubic if interpolation == "cubic" else _lerp
    return BoundingBox(
        x=ease(left.box.x, right.box.x, fraction),
        y=ease(left.box.y, right.box.y, fraction),
        width=ease(left.box.width, right.box.width, fraction),
        height=ease(left.box.height, right.box.height, fraction),
    )


def frame_at_ms(handle: MediaHandle, time_ms: int) -> VideoFrame:
    """Decode the video frame at a given time.

    Decoding uses ``av`` (the ``lairs[video]`` extra), imported lazily so
    importing this module never pulls in the heavy dependency.

    Parameters
    ----------
    handle : lairs.media.resolve.MediaHandle
        The resolved media handle to decode.
    time_ms : int
        The frame time in milliseconds.

    Returns
    -------
    VideoFrame
        The decoded frame nearest the requested time.

    Raises
    ------
    ModuleNotFoundError
        If the ``lairs[video]`` extra (``av``) is not installed.
    ValueError
        If the handle carries no bytes to decode or ``time_ms`` is negative.
    """
    if time_ms < 0:
        msg = f"time_ms must be non-negative, got {time_ms}"
        raise ValueError(msg)
    if not handle.data:
        msg = "media handle has no bytes to decode; resolve it first"
        raise ValueError(msg)
    try:
        import io  # noqa: PLC0415

        import av  # noqa: PLC0415  # ty: ignore[unresolved-import]
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via test patch
        msg = "video decoding requires the lairs[video] extra (av)"
        raise ModuleNotFoundError(msg) from exc
    container = av.open(io.BytesIO(handle.data))
    target_s = time_ms / 1000.0
    stream = container.streams.video[0]
    chosen_index = 0
    width = 0
    height = 0
    pixels = b""
    for index, frame in enumerate(container.decode(stream)):
        chosen_index = index
        width = frame.width
        height = frame.height
        pixels = bytes(frame.to_ndarray(format="rgb24").tobytes())
        if frame.time is not None and frame.time >= target_s:
            break
    container.close()
    return VideoFrame(index=chosen_index, width=width, height=height, pixels=pixels)


def crop_to_bbox(frame: VideoFrame, box: BoundingBox) -> VideoFrame:
    """Crop a frame to a bounding box.

    The crop math is pure Python (it only adjusts the frame dimensions and
    slices the row-major RGB payload), so it does not require the video extra.

    Parameters
    ----------
    frame : VideoFrame
        The frame to crop.
    box : BoundingBox
        The crop region in pixel coordinates.

    Returns
    -------
    VideoFrame
        The cropped frame.

    Raises
    ------
    ValueError
        If the box falls outside the frame bounds.
    """
    left = int(box.x)
    top = int(box.y)
    right = int(box.x + box.width)
    bottom = int(box.y + box.height)
    if left < 0 or top < 0 or right > frame.width or bottom > frame.height:
        msg = "bounding box falls outside the frame bounds"
        raise ValueError(msg)
    new_width = right - left
    new_height = bottom - top
    cropped = bytearray()
    if frame.pixels:
        channels = 3
        stride = frame.width * channels
        for row in range(top, bottom):
            start = row * stride + left * channels
            cropped.extend(frame.pixels[start : start + new_width * channels])
    return frame.with_(width=new_width, height=new_height, pixels=bytes(cropped))
