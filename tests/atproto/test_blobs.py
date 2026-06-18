"""Unit and integration tests for lairs.atproto.blobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto import blobs
from lairs.atproto.blobs import BlobBytes, BlobClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import PdsServer

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
def test_blob_round_trip_live(pds_server: PdsServer) -> None:
    """Upload a blob, bind it to a record, and fetch it back by CID."""
    payload = b"the audio bytes" * 64
    auth = {"Authorization": f"Bearer {pds_server.access_jwt}"}
    with httpx.Client(headers=auth) as authed:
        uploaded = authed.post(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.uploadBlob",
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
            timeout=30.0,
        )
        uploaded.raise_for_status()
        blob_ref = uploaded.json()["blob"]
        cid = str(blob_ref["ref"]["$link"])
        # an unreferenced blob is not retained, so bind it to a media record.
        bound = authed.post(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": pds_server.did,
                "collection": "pub.layers.media.media",
                "record": {
                    "$type": "pub.layers.media.media",
                    "kind": "audio",
                    "blob": blob_ref,
                    "createdAt": "2026-06-16T00:00:00Z",
                },
            },
            timeout=30.0,
        )
        bound.raise_for_status()
    fetched = BlobClient(pds_server.endpoint).get_blob(pds_server.did, cid)
    assert fetched.cid == cid
    assert fetched.data == payload


@pytest.mark.integration
def test_large_blob_round_trip_live(pds_server: PdsServer) -> None:
    # a multi-megabyte blob round-trips by CID, and the streamed read
    # reassembles to the same bytes as the buffered read.
    payload = bytes(range(256)) * 12000  # ~3 MiB of varied bytes
    auth = {"Authorization": f"Bearer {pds_server.access_jwt}"}
    with httpx.Client(headers=auth) as authed:
        uploaded = authed.post(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.uploadBlob",
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
            timeout=60.0,
        )
        uploaded.raise_for_status()
        blob_ref = uploaded.json()["blob"]
        cid = str(blob_ref["ref"]["$link"])
        bound = authed.post(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": pds_server.did,
                "collection": "pub.layers.media.media",
                "record": {
                    "$type": "pub.layers.media.media",
                    "kind": "audio",
                    "blob": blob_ref,
                    "createdAt": "2026-06-16T00:00:00Z",
                },
            },
            timeout=30.0,
        )
        bound.raise_for_status()
    client = BlobClient(pds_server.endpoint)
    fetched = client.get_blob(pds_server.did, cid)
    assert fetched.data == payload
    streamed = b"".join(client.iter_blob(pds_server.did, cid))
    assert streamed == payload
