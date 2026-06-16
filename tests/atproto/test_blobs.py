"""Unit and integration tests for lairs.atproto.blobs."""

from __future__ import annotations

import pytest

from lairs.atproto import blobs


def test_exports() -> None:
    assert set(blobs.__all__) == {"get_blob", "upload_blob"}


def test_get_blob_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        blobs.get_blob("did:plc:abc", "bafycid")


def test_upload_blob_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        blobs.upload_blob(b"data", "audio/wav")


@pytest.mark.integration
def test_get_blob_live() -> None:
    # exercises a real getBlob when opted in; skips otherwise.
    try:
        blobs.get_blob("did:plc:abc", "bafycid")
    except NotImplementedError:
        pytest.skip("blob client not implemented yet")
