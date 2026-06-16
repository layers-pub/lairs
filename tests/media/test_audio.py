"""Unit and integration tests for lairs.media.audio."""

from __future__ import annotations

import pytest

from lairs.media import audio
from lairs.media.audio import AudioBuffer
from lairs.media.resolve import MediaHandle


def test_exports() -> None:
    assert set(audio.__all__) == {"AudioBuffer", "decode_audio", "slice_by_temporal"}


def test_audio_buffer_construction() -> None:
    buf = AudioBuffer(sample_rate=16000, channels=1)
    assert buf.sample_rate == 16000
    assert buf.channels == 1


def test_decode_audio_is_a_stub() -> None:
    handle = MediaHandle(cid="bafy", mime_type="audio/wav", modality="audio")
    with pytest.raises(NotImplementedError):
        audio.decode_audio(handle)


def test_slice_by_temporal_is_a_stub() -> None:
    buf = AudioBuffer(sample_rate=16000, channels=1)
    with pytest.raises(NotImplementedError):
        audio.slice_by_temporal(buf, 0, 100)


@pytest.mark.integration
def test_decode_audio_live() -> None:
    pytest.importorskip("soundfile")
    pytest.skip("requires an audio fixture")
