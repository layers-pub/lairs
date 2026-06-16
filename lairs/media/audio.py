"""Audio decoding and temporal-span slicing.

Decodes audio into a sample buffer and slices it by temporal-span anchors,
converting milliseconds to sample indices in a rate-aware way. The buffer is a
didactic model carrying the samples in an opaque field. The decode path
requires the ``lairs[audio]`` extra (``soundfile``) at runtime, but the
millisecond-to-sample math and slicing are pure Python and need no extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from lairs.media.resolve import MediaHandle

__all__ = [
    "AudioBuffer",
    "decode_audio",
    "forced_alignment_segments",
    "ms_to_sample",
    "sample_to_ms",
    "slice_by_temporal",
]


class AudioBuffer(dx.Model):
    """A decoded audio buffer.

    Samples are stored interleaved by channel as a flat tuple of floats: for a
    two-channel buffer the layout is ``(l0, r0, l1, r1, ...)``. The payload
    lives in an opaque field so callers go through the typed helpers rather than
    inspecting it blindly.

    Parameters
    ----------
    sample_rate : int
        The sample rate in hertz.
    channels : int
        The channel count.
    samples : tuple of float, optional
        The interleaved samples, carried as an opaque payload.
    """

    sample_rate: int = dx.field(description="sample rate in hertz")
    channels: int = dx.field(description="channel count")
    samples: tuple[float, ...] = dx.field(
        default=(),
        opaque=True,
        description="interleaved samples carried as an opaque payload",
    )


def ms_to_sample(ms: int, sample_rate: int) -> int:
    """Convert a millisecond offset to a per-channel sample index.

    Parameters
    ----------
    ms : int
        The offset in milliseconds.
    sample_rate : int
        The sample rate in hertz.

    Returns
    -------
    int
        The per-channel sample index, floored to a whole sample.

    Raises
    ------
    ValueError
        If ``ms`` is negative or ``sample_rate`` is not positive.
    """
    if ms < 0:
        msg = f"ms must be non-negative, got {ms}"
        raise ValueError(msg)
    if sample_rate <= 0:
        msg = f"sample_rate must be positive, got {sample_rate}"
        raise ValueError(msg)
    return (ms * sample_rate) // 1000


def sample_to_ms(sample: int, sample_rate: int) -> int:
    """Convert a per-channel sample index to a millisecond offset.

    Parameters
    ----------
    sample : int
        The per-channel sample index.
    sample_rate : int
        The sample rate in hertz.

    Returns
    -------
    int
        The offset in milliseconds, floored to a whole millisecond.

    Raises
    ------
    ValueError
        If ``sample`` is negative or ``sample_rate`` is not positive.
    """
    if sample < 0:
        msg = f"sample must be non-negative, got {sample}"
        raise ValueError(msg)
    if sample_rate <= 0:
        msg = f"sample_rate must be positive, got {sample_rate}"
        raise ValueError(msg)
    return (sample * 1000) // sample_rate


def decode_audio(handle: MediaHandle) -> AudioBuffer:
    """Decode a media handle into an audio buffer.

    Decoding uses ``soundfile`` (the ``lairs[audio]`` extra), imported lazily
    so importing this module never pulls in the heavy dependency.

    Parameters
    ----------
    handle : lairs.media.resolve.MediaHandle
        The resolved media handle to decode.

    Returns
    -------
    AudioBuffer
        The decoded audio buffer with interleaved samples.

    Raises
    ------
    ModuleNotFoundError
        If the ``lairs[audio]`` extra (``soundfile``) is not installed.
    ValueError
        If the handle carries no bytes to decode.
    """
    if not handle.data:
        msg = "media handle has no bytes to decode; resolve it first"
        raise ValueError(msg)
    try:
        import io  # noqa: PLC0415

        import soundfile  # noqa: PLC0415  # ty: ignore[unresolved-import]
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via test patch
        msg = "audio decoding requires the lairs[audio] extra (soundfile)"
        raise ModuleNotFoundError(msg) from exc
    data, rate = soundfile.read(io.BytesIO(handle.data), always_2d=True)
    channels = len(data[0]) if len(data) else 1
    flat: list[float] = [float(value) for row in data for value in row]
    return AudioBuffer(sample_rate=int(rate), channels=channels, samples=tuple(flat))


def slice_by_temporal(buffer: AudioBuffer, start_ms: int, end_ms: int) -> AudioBuffer:
    """Slice an audio buffer by a temporal span in milliseconds.

    The span is converted to per-channel sample indices in a rate-aware way and
    the interleaved payload is sliced accordingly. This is pure Python and does
    not require the audio extra.

    Parameters
    ----------
    buffer : AudioBuffer
        The buffer to slice.
    start_ms : int
        The start of the span in milliseconds.
    end_ms : int
        The end of the span in milliseconds.

    Returns
    -------
    AudioBuffer
        A new buffer holding only the samples in the span.

    Raises
    ------
    ValueError
        If the span is reversed (``end_ms`` before ``start_ms``).
    """
    if end_ms < start_ms:
        msg = f"end_ms ({end_ms}) must not precede start_ms ({start_ms})"
        raise ValueError(msg)
    start_frame = ms_to_sample(start_ms, buffer.sample_rate)
    end_frame = ms_to_sample(end_ms, buffer.sample_rate)
    width = max(buffer.channels, 1)
    sliced = buffer.samples[start_frame * width : end_frame * width]
    return buffer.with_(samples=sliced)


def forced_alignment_segments(
    buffer: AudioBuffer,
    spans: Iterable[tuple[int, int, str]],
) -> Iterator[tuple[str, AudioBuffer]]:
    """Yield labelled waveform segments for a forced-alignment layer.

    Each input span is a ``(start_ms, end_ms, label)`` triple, mirroring an
    aligned annotation; the corresponding waveform slice is produced lazily.

    Parameters
    ----------
    buffer : AudioBuffer
        The buffer to segment.
    spans : iterable of tuple of (int, int, str)
        The ``(start_ms, end_ms, label)`` triples to align.

    Yields
    ------
    tuple of (str, AudioBuffer)
        Each label paired with its waveform segment.
    """
    for start_ms, end_ms, label in spans:
        yield label, slice_by_temporal(buffer, start_ms, end_ms)
