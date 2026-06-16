"""Unit and integration tests for lairs.integrations.codecs.brat."""

from __future__ import annotations

import pytest

from lairs.integrations.codecs.brat import BratCodec


def test_name() -> None:
    assert BratCodec.name == "brat"


def test_decode_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        BratCodec().decode("")


def test_encode_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        BratCodec().encode([])


@pytest.mark.integration
def test_roundtrip_live() -> None:
    pytest.skip("requires a brat standoff fixture corpus")
