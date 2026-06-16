"""Neural and time-series signal windowing.

Treats neural and sensor signals as sampling-rate-aware buffers referenced by
a media record, and windows them by temporal-span anchors. The signal buffer
is a didactic model carrying samples in an opaque field. Requires the
``lairs[neural]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from lairs.media.resolve import MediaHandle

__all__ = ["SignalBuffer", "decode_signal", "window_by_temporal"]


class SignalBuffer(dx.Model):
    """A decoded multi-channel signal buffer.

    Parameters
    ----------
    sample_rate : float
        The sample rate in hertz.
    channels : tuple of str
        The ordered channel labels.
    samples : bytes, optional
        The interleaved samples, carried as an opaque payload.
    """

    sample_rate: float = dx.field(description="sample rate in hertz")
    channels: tuple[str, ...] = dx.field(description="ordered channel labels")
    samples: bytes = dx.field(
        default=b"",
        opaque=True,
        description="interleaved samples carried as an opaque payload",
    )


def decode_signal(handle: MediaHandle) -> SignalBuffer:
    """Decode a media handle into a signal buffer.

    Parameters
    ----------
    handle : lairs.media.resolve.MediaHandle
        The resolved media handle to decode.

    Returns
    -------
    SignalBuffer
        The decoded signal buffer.

    Raises
    ------
    NotImplementedError
        Always, until the neural layer lands.
    """
    raise NotImplementedError


def window_by_temporal(
    buffer: SignalBuffer,
    start_ms: int,
    end_ms: int,
) -> SignalBuffer:
    """Window a signal buffer by a temporal span.

    Parameters
    ----------
    buffer : SignalBuffer
        The buffer to window.
    start_ms : int
        The window start in milliseconds.
    end_ms : int
        The window end in milliseconds.

    Returns
    -------
    SignalBuffer
        The windowed buffer.

    Raises
    ------
    NotImplementedError
        Always, until the neural layer lands.
    """
    raise NotImplementedError
