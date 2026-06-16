"""Audio decoding and temporal-span slicing.

Decodes audio into a sample buffer and slices it by temporal-span anchors,
converting milliseconds to sample indices in a rate-aware way. The buffer is a
didactic model carrying the samples in an opaque field. Requires the
``lairs[audio]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from lairs.media.resolve import MediaHandle

__all__ = ["AudioBuffer", "decode_audio", "slice_by_temporal"]


class AudioBuffer(dx.Model):
    """A decoded audio buffer.

    Parameters
    ----------
    sample_rate : int
        The sample rate in hertz.
    channels : int
        The channel count.
    samples : bytes, optional
        The interleaved samples, carried as an opaque payload.
    """

    sample_rate: int = dx.field(description="sample rate in hertz")
    channels: int = dx.field(description="channel count")
    samples: bytes = dx.field(
        default=b"",
        opaque=True,
        description="interleaved samples carried as an opaque payload",
    )


def decode_audio(handle: MediaHandle) -> AudioBuffer:
    """Decode a media handle into an audio buffer.

    Parameters
    ----------
    handle : lairs.media.resolve.MediaHandle
        The resolved media handle to decode.

    Returns
    -------
    AudioBuffer
        The decoded audio buffer.

    Raises
    ------
    NotImplementedError
        Always, until the audio layer lands.
    """
    raise NotImplementedError


def slice_by_temporal(buffer: AudioBuffer, start_ms: int, end_ms: int) -> AudioBuffer:
    """Slice an audio buffer by a temporal span.

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
        The sliced buffer.

    Raises
    ------
    NotImplementedError
        Always, until the audio layer lands.
    """
    raise NotImplementedError
