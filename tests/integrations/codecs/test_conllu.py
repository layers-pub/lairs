"""Unit and integration tests for lairs.integrations.codecs.conllu."""

from __future__ import annotations

import pytest

from lairs.integrations.codecs.conllu import ConlluCodec


def test_name() -> None:
    assert ConlluCodec.name == "conllu"


def test_decode_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        ConlluCodec().decode("")


def test_encode_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        ConlluCodec().encode([])


@pytest.mark.integration
def test_roundtrip_live() -> None:
    pytest.importorskip("conllu")
    pytest.skip("requires a conllu fixture corpus")
