"""Video decoding, frame access, and bounding-box cropping.

Decodes video frames by time or index, crops frames to bounding boxes, and
resolves spatio-temporal anchors to dense per-frame boxes through keyframe
interpolation. Frames are didactic models carrying pixels in an opaque field.
Requires the ``lairs[video]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from lairs.media.resolve import MediaHandle

__all__ = ["VideoFrame", "crop_to_bbox", "frame_at_ms"]


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


def frame_at_ms(handle: MediaHandle, time_ms: int) -> VideoFrame:
    """Decode the video frame at a given time.

    Parameters
    ----------
    handle : lairs.media.resolve.MediaHandle
        The resolved media handle to decode.
    time_ms : int
        The frame time in milliseconds.

    Returns
    -------
    VideoFrame
        The decoded frame.

    Raises
    ------
    NotImplementedError
        Always, until the video layer lands.
    """
    raise NotImplementedError


def crop_to_bbox(
    frame: VideoFrame,
    x: float,
    y: float,
    width: float,
    height: float,
) -> VideoFrame:
    """Crop a frame to a bounding box.

    Parameters
    ----------
    frame : VideoFrame
        The frame to crop.
    x : float
        The left coordinate in pixels.
    y : float
        The top coordinate in pixels.
    width : float
        The box width in pixels.
    height : float
        The box height in pixels.

    Returns
    -------
    VideoFrame
        The cropped frame.

    Raises
    ------
    NotImplementedError
        Always, until the video layer lands.
    """
    raise NotImplementedError
