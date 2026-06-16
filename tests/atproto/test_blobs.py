"""Unit and integration tests for lairs.atproto.blobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto import blobs
from lairs.atproto.blobs import BlobBytes, BlobClient

if TYPE_CHECKING:
    from collections.abc import Callable

_ENDPOINT = "https://pds.example"
_DID = "did:plc:abc"
_CID = "bafyblob"
_PAYLOAD = b"the blob bytes" * 8


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> BlobClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return BlobClient(_ENDPOINT, client)


def test_exports() -> None:
    assert set(blobs.__all__) == {
        "BlobBytes",
        "BlobClient",
        "get_blob",
        "upload_blob",
    }


def test_get_blob_streams_and_addresses_by_cid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.sync.getBlob"
        assert request.url.params["did"] == _DID
        assert request.url.params["cid"] == _CID
        return httpx.Response(
            200,
            content=_PAYLOAD,
            headers={"content-type": "audio/wav"},
        )

    with _client(handler) as client:
        blob = client.get_blob(_DID, _CID)
    assert isinstance(blob, BlobBytes)
    assert blob.did == _DID
    assert blob.cid == _CID
    assert blob.data == _PAYLOAD
    assert blob.mime_type == "audio/wav"


def test_iter_blob_yields_chunks() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_PAYLOAD)

    with _client(handler) as client:
        joined = b"".join(client.iter_blob(_DID, _CID))
    assert joined == _PAYLOAD


def test_get_blob_raises_on_error_status() -> None:
    with (
        _client(lambda _r: httpx.Response(404)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.get_blob(_DID, _CID)


def test_upload_blob_is_deferred_to_authoring() -> None:
    with pytest.raises(NotImplementedError):
        blobs.upload_blob(b"data", "audio/wav")


@pytest.mark.integration
def test_get_blob_live() -> None:
    # exercises a real getBlob when opted in; skips otherwise.
    try:
        blobs.get_blob(_ENDPOINT, _DID, _CID)
    except httpx.HTTPError:
        pytest.skip("network unavailable for live getBlob")
