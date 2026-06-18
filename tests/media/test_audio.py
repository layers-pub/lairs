"""Unit and integration tests for lairs.media.audio."""

from __future__ import annotations

import io

import pytest

from lairs.media import audio
from lairs.media.audio import (
    AudioBuffer,
    decode_audio,
    forced_alignment_segments,
    ms_to_sample,
    sample_to_ms,
    slice_by_temporal,
)
from lairs.media.resolve import MediaHandle


def test_exports() -> None:
    assert set(audio.__all__) == {
        "AudioBuffer",
        "decode_audio",
        "forced_alignment_segments",
        "ms_to_sample",
        "sample_to_ms",
        "slice_by_temporal",
    }


def test_audio_buffer_construction() -> None:
    buf = AudioBuffer(sample_rate=16000, channels=1)
    assert buf.sample_rate == 16000
    assert buf.channels == 1
    assert buf.samples == ()


def test_ms_to_sample_is_rate_aware() -> None:
    assert ms_to_sample(1000, 16000) == 16000
    assert ms_to_sample(500, 16000) == 8000
    assert ms_to_sample(0, 44100) == 0
    # floors a sub-sample offset
    assert ms_to_sample(1, 100) == 0


def test_sample_to_ms_round_trip() -> None:
    assert sample_to_ms(16000, 16000) == 1000
    assert sample_to_ms(8000, 16000) == 500


def test_ms_to_sample_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ms_to_sample(-1, 16000)
    with pytest.raises(ValueError, match="positive"):
        ms_to_sample(10, 0)


def test_slice_by_temporal_mono() -> None:
    buf = AudioBuffer(
        sample_rate=10, channels=1, samples=tuple(float(i) for i in range(10))
    )
    sliced = slice_by_temporal(buf, 0, 500)
    assert sliced.samples == (0.0, 1.0, 2.0, 3.0, 4.0)
    assert sliced.sample_rate == 10
    # the source buffer is unchanged (models are immutable)
    assert len(buf.samples) == 10


def test_slice_by_temporal_stereo_is_interleave_aware() -> None:
    buf = AudioBuffer(
        sample_rate=10, channels=2, samples=tuple(float(i) for i in range(20))
    )
    sliced = slice_by_temporal(buf, 0, 500)
    # 5 frames * 2 channels = 10 interleaved samples
    assert sliced.samples == tuple(float(i) for i in range(10))


def test_slice_by_temporal_rejects_reversed_span() -> None:
    buf = AudioBuffer(sample_rate=10, channels=1, samples=(1.0,))
    with pytest.raises(ValueError, match="must not precede"):
        slice_by_temporal(buf, 500, 0)


def test_forced_alignment_segments() -> None:
    buf = AudioBuffer(
        sample_rate=10, channels=1, samples=tuple(float(i) for i in range(10))
    )
    segments = list(forced_alignment_segments(buf, [(0, 500, "a"), (500, 1000, "b")]))
    assert [label for label, _ in segments] == ["a", "b"]
    assert segments[0][1].samples == (0.0, 1.0, 2.0, 3.0, 4.0)
    assert segments[1][1].samples == (5.0, 6.0, 7.0, 8.0, 9.0)


def test_decode_audio_rejects_empty_handle() -> None:
    handle = MediaHandle(cid="bafy", mime_type="audio/wav", modality="audio")
    with pytest.raises(ValueError, match="no bytes to decode"):
        decode_audio(handle)


@pytest.mark.integration
def test_decode_audio_live() -> None:
    # synthesize a tiny stereo WAV in memory so the soundfile decode path runs
    # without depending on an external fixture file.
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    buffer = io.BytesIO()
    frames = np.array(
        [[0.0, 0.0], [0.25, -0.25], [0.5, -0.5], [0.75, -0.75]],
        dtype="float32",
    )
    sf.write(buffer, frames, 16000, format="WAV")
    handle = MediaHandle(
        cid="bafy",
        mime_type="audio/wav",
        modality="audio",
        data=buffer.getvalue(),
    )
    decoded = decode_audio(handle)
    assert decoded.sample_rate == 16000
    assert decoded.channels == 2
    # four stereo frames interleave to eight samples.
    assert len(decoded.samples) == 8
