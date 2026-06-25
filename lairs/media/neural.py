"""Neural and time-series signal windowing.

Treats neural and sensor signals as sampling-rate-aware, multi-channel buffers
referenced by a media record, and windows them by temporal-span anchors. The
signal buffer is a didactic model carrying per-channel samples in an opaque
field. The decode path requires the ``lairs[neural]`` extra (``mne``) at
runtime, but the millisecond-to-window math and slicing are pure Python and
need no extra.

``decode_signal`` dispatches on the handle's MIME type to the matching ``mne``
reader and temp-file suffix (FIF, EDF, BDF, EEGLAB SET, BrainVision). A MIME
type ``mne`` cannot read raises a clear error rather than being mis-read as FIF.
"""

from __future__ import annotations

import tempfile
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from lairs.media.resolve import MediaHandle

__all__ = [
    "SignalBuffer",
    "align_events_to_windows",
    "decode_signal",
    "ms_to_sample",
    "select_channels",
    "window_by_temporal",
]

# MIME type (lowercased) -> (mne reader attribute, temp-file suffix). The MIME
# vocabulary for biosignal formats is not standardized, so common variants and
# the bare extension-style tokens are all mapped to the same reader.
_SIGNAL_READERS: dict[str, tuple[str, str]] = {
    "application/x-fif": ("read_raw_fif", "_raw.fif"),
    "application/fif": ("read_raw_fif", "_raw.fif"),
    "application/x-edf": ("read_raw_edf", ".edf"),
    "application/edf": ("read_raw_edf", ".edf"),
    "application/x-bdf": ("read_raw_bdf", ".bdf"),
    "application/bdf": ("read_raw_bdf", ".bdf"),
    "application/x-eeglab": ("read_raw_eeglab", ".set"),
    "application/set": ("read_raw_eeglab", ".set"),
    "application/x-brainvision": ("read_raw_brainvision", ".vhdr"),
    "application/brainvision": ("read_raw_brainvision", ".vhdr"),
}

# bare format/extension tokens recovered from a MIME subtype, for handles whose
# mime_type is a generic octet-stream carrying only the format name.
_SIGNAL_SUFFIX_READERS: dict[str, tuple[str, str]] = {
    "fif": ("read_raw_fif", "_raw.fif"),
    "edf": ("read_raw_edf", ".edf"),
    "bdf": ("read_raw_bdf", ".bdf"),
    "set": ("read_raw_eeglab", ".set"),
    "vhdr": ("read_raw_brainvision", ".vhdr"),
    "brainvision": ("read_raw_brainvision", ".vhdr"),
}


def _reader_for(mime_type: str) -> tuple[str, str]:
    """Return the ``mne`` reader attribute and temp suffix for a MIME type.

    Raises
    ------
    ValueError
        If no ``mne`` reader is known for the MIME type.
    """
    token = mime_type.strip().lower()
    if token in _SIGNAL_READERS:
        return _SIGNAL_READERS[token]
    subtype = token.rsplit("/", 1)[-1].removeprefix("x-")
    if subtype in _SIGNAL_SUFFIX_READERS:
        return _SIGNAL_SUFFIX_READERS[subtype]
    msg = (
        f"no signal reader for MIME type {mime_type!r}; supported formats are "
        "FIF, EDF, BDF, EEGLAB SET, and BrainVision"
    )
    raise ValueError(msg)


class SignalBuffer(dx.Model):
    """A decoded multi-channel signal buffer.

    Samples are stored per channel as a tuple of per-channel sample tuples,
    aligned with ``channels`` by position. The payload lives in an opaque field
    so callers go through the typed helpers rather than inspecting it blindly.

    Attributes
    ----------
    sample_rate : float
        The sample rate in hertz.
    channels : tuple of str
        The ordered channel labels.
    samples : tuple of tuple of float, optional
        The per-channel samples, carried as an opaque payload.
    """

    sample_rate: float = dx.field(description="sample rate in hertz")
    channels: tuple[str, ...] = dx.field(description="ordered channel labels")
    samples: tuple[tuple[float, ...], ...] = dx.field(
        default=(),
        opaque=True,
        description="per-channel samples carried as an opaque payload",
    )


def ms_to_sample(ms: int, sample_rate: float) -> int:
    """Convert a millisecond offset to a sample index for a given rate.

    Parameters
    ----------
    ms : int
        The offset in milliseconds.
    sample_rate : float
        The sample rate in hertz.

    Returns
    -------
    int
        The sample index, floored to a whole sample.

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
    return int(ms * sample_rate / 1000.0)


def decode_signal(handle: MediaHandle) -> SignalBuffer:
    """Decode a media handle into a multi-channel signal buffer.

    Decoding uses ``mne`` (the ``lairs[neural]`` extra), imported lazily so
    importing this module never pulls in the heavy dependency. The handle's MIME
    type selects the matching ``mne`` reader (FIF, EDF, BDF, EEGLAB SET, or
    BrainVision) and temp-file suffix; the raw bytes are written to a temporary
    file because ``mne`` readers operate on paths.

    The temporary file is created, written, closed, read, and then removed
    explicitly (rather than read while still open) so the path can be reopened by
    ``mne`` on platforms that do not allow concurrent reopen of an open temp file.

    Parameters
    ----------
    handle : lairs.media.resolve.MediaHandle
        The resolved media handle to decode.

    Returns
    -------
    SignalBuffer
        The decoded signal buffer with per-channel samples.

    Raises
    ------
    ModuleNotFoundError
        If the ``lairs[neural]`` extra (``mne``) is not installed.
    ValueError
        If the handle carries no bytes to decode, or its MIME type names a
        format no ``mne`` reader supports.
    """
    if not handle.data:
        msg = "media handle has no bytes to decode; resolve it first"
        raise ValueError(msg)
    reader_name, suffix = _reader_for(handle.mime_type)
    try:
        import mne  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via test patch
        msg = "signal decoding requires the lairs[neural] extra (mne)"
        raise ModuleNotFoundError(msg) from exc
    read_raw = getattr(mne.io, reader_name)
    # close the temp file before mne reopens it by name: some platforms do not
    # permit reopening a NamedTemporaryFile while the original handle is open.
    # delete_on_close=False keeps the file on disk after close so mne can read
    # it, while the context manager still removes it on exit.
    with tempfile.NamedTemporaryFile(suffix=suffix, delete_on_close=False) as tmp:
        tmp.write(handle.data)
        tmp.close()
        raw = read_raw(tmp.name, preload=True, verbose=False)
    data = raw.get_data()
    channels = tuple(str(name) for name in raw.ch_names)
    samples = tuple(tuple(float(value) for value in row) for row in data)
    return SignalBuffer(
        sample_rate=float(raw.info["sfreq"]),
        channels=channels,
        samples=samples,
    )


def window_by_temporal(
    buffer: SignalBuffer,
    start_ms: int,
    end_ms: int,
) -> SignalBuffer:
    """Window a signal buffer by a temporal span in milliseconds.

    The span is converted to sample indices in a rate-aware way and every
    channel is sliced to the same window. This is pure Python and does not
    require the neural extra.

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
        A new buffer holding only the samples in the window.

    Raises
    ------
    ValueError
        If the window is reversed (``end_ms`` before ``start_ms``).
    """
    if end_ms < start_ms:
        msg = f"end_ms ({end_ms}) must not precede start_ms ({start_ms})"
        raise ValueError(msg)
    start = ms_to_sample(start_ms, buffer.sample_rate)
    end = ms_to_sample(end_ms, buffer.sample_rate)
    windowed = tuple(channel[start:end] for channel in buffer.samples)
    return buffer.with_(samples=windowed)


def select_channels(buffer: SignalBuffer, names: Sequence[str]) -> SignalBuffer:
    """Select a subset of channels by label, preserving the requested order.

    Parameters
    ----------
    buffer : SignalBuffer
        The buffer to subset.
    names : sequence of str
        The channel labels to keep, in the desired output order.

    Returns
    -------
    SignalBuffer
        A new buffer holding only the named channels.

    Raises
    ------
    KeyError
        If a requested channel label is not present in the buffer.
    """
    index_of = {label: position for position, label in enumerate(buffer.channels)}
    selected_rows: list[tuple[float, ...]] = []
    for name in names:
        if name not in index_of:
            msg = f"channel {name!r} not in buffer"
            raise KeyError(msg)
        position = index_of[name]
        if position < len(buffer.samples):
            selected_rows.append(buffer.samples[position])
        else:
            selected_rows.append(())
    return buffer.with_(channels=tuple(names), samples=tuple(selected_rows))


def align_events_to_windows(
    buffer: SignalBuffer,
    events: Iterable[tuple[int, int, str]],
) -> Iterator[tuple[str, SignalBuffer]]:
    """Yield labelled signal windows for a sequence of annotation events.

    Each event is a ``(start_ms, end_ms, label)`` triple, mirroring an aligned
    annotation (a stimulus onset, an epoch); the corresponding multi-channel
    window is produced lazily.

    Parameters
    ----------
    buffer : SignalBuffer
        The buffer to window.
    events : iterable of tuple of (int, int, str)
        The ``(start_ms, end_ms, label)`` triples to align.

    Yields
    ------
    tuple of (str, SignalBuffer)
        Each label paired with its signal window.
    """
    for start_ms, end_ms, label in events:
        yield label, window_by_temporal(buffer, start_ms, end_ms)
