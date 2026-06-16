"""Unit and integration tests for lairs.media.neural."""

from __future__ import annotations

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
    handle = MediaHandle(
        cid="bafy", mime_type="application/octet-stream", modality="audio"
    )
    with pytest.raises(ValueError, match="no bytes to decode"):
        decode_signal(handle)


@pytest.mark.integration
def test_decode_signal_live() -> None:
    pytest.importorskip("mne")
    pytest.skip("requires a signal fixture")
