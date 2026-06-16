"""Unit and integration tests for lairs.media.video."""

from __future__ import annotations

import pytest

from lairs.media import video
from lairs.media.resolve import MediaHandle
from lairs.media.video import VideoFrame


def test_exports() -> None:
    assert set(video.__all__) == {"VideoFrame", "crop_to_bbox", "frame_at_ms"}


def test_video_frame_construction() -> None:
    frame = VideoFrame(index=0, width=640, height=480)
    assert frame.index == 0
    assert frame.width == 640


def test_frame_at_ms_is_a_stub() -> None:
    handle = MediaHandle(cid="bafy", mime_type="video/mp4", modality="video")
    with pytest.raises(NotImplementedError):
        video.frame_at_ms(handle, 100)


def test_crop_to_bbox_is_a_stub() -> None:
    frame = VideoFrame(index=0, width=640, height=480)
    with pytest.raises(NotImplementedError):
        video.crop_to_bbox(frame, 0.0, 0.0, 10.0, 10.0)


@pytest.mark.integration
def test_frame_at_ms_live() -> None:
    pytest.importorskip("av")
    pytest.skip("requires a video fixture")
