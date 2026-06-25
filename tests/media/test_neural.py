"""Unit and integration tests for lairs.media.neural."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from lairs.media import neural
from lairs.media.neural import (
    SignalBuffer,
    align_events_to_windows,
    decode_signal,
    ms_to_sample,
    select_channels,
    window_by_temporal,
)
from lairs.media.resolve import MediaHandle


def test_exports() -> None:
    assert set(neural.__all__) == {
        "SignalBuffer",
        "align_events_to_windows",
        "decode_signal",
        "ms_to_sample",
        "select_channels",
        "window_by_temporal",
    }


def test_signal_buffer_construction() -> None:
    buf = SignalBuffer(sample_rate=256.0, channels=("Fz", "Cz"))
    assert buf.sample_rate == 256.0
    assert buf.channels == ("Fz", "Cz")
    assert buf.samples == ()


def test_ms_to_sample_is_rate_aware() -> None:
    assert ms_to_sample(1000, 256.0) == 256
    assert ms_to_sample(500, 256.0) == 128
    assert ms_to_sample(20, 100.0) == 2


def test_ms_to_sample_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ms_to_sample(-1, 256.0)
    with pytest.raises(ValueError, match="positive"):
        ms_to_sample(10, 0.0)


def _signal() -> SignalBuffer:
    return SignalBuffer(
        sample_rate=100.0,
        channels=("a", "b"),
        samples=((0.0, 1.0, 2.0, 3.0, 4.0), (10.0, 11.0, 12.0, 13.0, 14.0)),
    )


def test_window_by_temporal_multichannel() -> None:
    windowed = window_by_temporal(_signal(), 0, 20)
    # 20 ms at 100 hz = 2 samples per channel
    assert windowed.samples == ((0.0, 1.0), (10.0, 11.0))
    assert windowed.channels == ("a", "b")


def test_window_by_temporal_rejects_reversed() -> None:
    with pytest.raises(ValueError, match="must not precede"):
        window_by_temporal(_signal(), 50, 0)


def test_select_channels_preserves_requested_order() -> None:
    selected = select_channels(_signal(), ("b",))
    assert selected.channels == ("b",)
    assert selected.samples == ((10.0, 11.0, 12.0, 13.0, 14.0),)


def test_select_channels_can_reorder() -> None:
    selected = select_channels(_signal(), ("b", "a"))
    assert selected.channels == ("b", "a")
    assert selected.samples == (
        (10.0, 11.0, 12.0, 13.0, 14.0),
        (0.0, 1.0, 2.0, 3.0, 4.0),
    )


def test_select_channels_unknown_label_raises() -> None:
    with pytest.raises(KeyError, match="not in buffer"):
        select_channels(_signal(), ("zz",))


def test_align_events_to_windows() -> None:
    events = [(0, 20, "onset"), (20, 40, "epoch")]
    windows = list(align_events_to_windows(_signal(), events))
    assert [label for label, _ in windows] == ["onset", "epoch"]
    assert windows[0][1].samples == ((0.0, 1.0), (10.0, 11.0))
    assert windows[1][1].samples == ((2.0, 3.0), (12.0, 13.0))


def test_decode_signal_rejects_empty_handle() -> None:
    handle = MediaHandle(cid="bafy", mime_type="application/x-fif", modality="audio")
    with pytest.raises(ValueError, match="no bytes to decode"):
        decode_signal(handle)


def test_decode_signal_rejects_unknown_format() -> None:
    handle = MediaHandle(
        cid="bafy",
        mime_type="application/octet-stream",
        modality="audio",
        data=b"not a recognised signal",
    )
    with pytest.raises(ValueError, match="no signal reader"):
        decode_signal(handle)


@pytest.mark.parametrize(
    ("mime_type", "reader", "suffix"),
    [
        ("application/x-fif", "read_raw_fif", "_raw.fif"),
        ("application/x-edf", "read_raw_edf", ".edf"),
        ("application/x-bdf", "read_raw_bdf", ".bdf"),
        ("application/x-eeglab", "read_raw_eeglab", ".set"),
        ("application/x-brainvision", "read_raw_brainvision", ".vhdr"),
        # generic octet-stream carrying only the format name in the subtype
        ("application/edf", "read_raw_edf", ".edf"),
        ("application/x-vhdr", "read_raw_brainvision", ".vhdr"),
    ],
)
def test_reader_for_dispatches_by_mime_type(
    mime_type: str, reader: str, suffix: str
) -> None:
    assert neural._reader_for(mime_type) == (reader, suffix)


def test_reader_for_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="no signal reader"):
        neural._reader_for("application/octet-stream")


@pytest.mark.integration
def test_decode_signal_live() -> None:
    # synthesize a tiny two-channel FIF recording so the mne decode path runs
    # without depending on an external fixture file.
    mne = pytest.importorskip("mne")
    np = pytest.importorskip("numpy")
    info = mne.create_info(ch_names=["eeg1", "eeg2"], sfreq=100.0, ch_types="eeg")
    rng = np.random.default_rng(0)
    raw = mne.io.RawArray(rng.standard_normal((2, 50)) * 1e-6, info, verbose=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample_raw.fif"
        raw.save(path, overwrite=True, verbose=False)
        fif_bytes = path.read_bytes()
    handle = MediaHandle(
        cid="bafy",
        mime_type="application/x-fif",
        modality="audio",
        data=fif_bytes,
    )
    decoded = decode_signal(handle)
    assert decoded.channels == ("eeg1", "eeg2")
    assert decoded.sample_rate == 100.0
    assert len(decoded.samples) == 2
    assert len(decoded.samples[0]) == 50
