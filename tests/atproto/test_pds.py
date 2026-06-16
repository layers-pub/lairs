"""Unit and integration tests for lairs.atproto.pds."""

from __future__ import annotations

import pytest

from lairs.atproto import pds


def test_exports() -> None:
    assert set(pds.__all__) == {"get_record", "list_records"}


def test_get_record_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        pds.get_record("did:plc:abc", "pub.layers.expression.expression", "rkey")


def test_list_records_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        pds.list_records("did:plc:abc", "pub.layers.expression.expression")


@pytest.mark.integration
def test_get_record_live() -> None:
    # exercises a real PDS getRecord when opted in; skips otherwise.
    try:
        pds.get_record("did:plc:abc", "pub.layers.corpus.corpus", "rkey")
    except NotImplementedError:
        pytest.skip("pds client not implemented yet")
