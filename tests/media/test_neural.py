"""Unit and integration tests for lairs.media.neural."""

from __future__ import annotations

import pytest

from lairs.media import neural
from lairs.media.neural import SignalBuffer
from lairs.media.resolve import MediaHandle


def test_exports() -> None:
    assert set(neural.__all__) == {
        "SignalBuffer",
        "decode_signal",
        "window_by_temporal",
    }


def test_signal_buffer_construction() -> None:
    buf = SignalBuffer(sample_rate=256.0, channels=("Fz", "Cz"))
    assert buf.sample_rate == 256.0
    assert buf.channels == ("Fz", "Cz")


def test_decode_signal_is_a_stub() -> None:
    handle = MediaHandle(
        cid="bafy", mime_type="application/octet-stream", modality="audio"
    )
    with pytest.raises(NotImplementedError):
        neural.decode_signal(handle)


def test_window_by_temporal_is_a_stub() -> None:
    buf = SignalBuffer(sample_rate=256.0, channels=("Fz",))
    with pytest.raises(NotImplementedError):
        neural.window_by_temporal(buf, 0, 100)


@pytest.mark.integration
def test_decode_signal_live() -> None:
    pytest.importorskip("mne")
    pytest.skip("requires a signal fixture")
