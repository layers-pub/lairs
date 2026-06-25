"""Blob fetch over ATProto.

Wraps ``com.atproto.sync.getBlob`` for streamed, content-addressed media bytes.
The returned ``BlobBytes`` holder carries the CID and the raw bytes (in an
opaque field) for the media layer to cache; this module does not implement the
cache, which is owned by the store and media components.

Blob upload (``com.atproto.repo.uploadBlob``) is a write and belongs to the
authoring component; it is a clearly-marked deferred stub here. The transport is
``httpx``; public reads need no auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import didactic.api as dx
import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

    from lairs.records.blobref import BlobRef

__all__ = ["BlobBytes", "BlobClient", "get_blob", "upload_blob"]

_GET_BLOB_NSID = "com.atproto.sync.getBlob"
"""The XRPC method for fetching blob bytes."""

_STREAM_CHUNK_SIZE = 65536
"""The chunk size, in bytes, used when streaming a blob."""


class BlobBytes(dx.Model):
    """A content-addressed holder of fetched blob bytes.

    The bytes are carried in an opaque field so the holder stays a ``dx.Model``
    while remaining a runtime container the media layer can cache by CID.

    Attributes
    ----------
    did : str
        The repository DID the blob was fetched from.
    cid : str
        The content identifier of the blob.
    data : bytes
        The raw blob bytes.
    mime_type : str or None, optional
        The MIME type reported by the PDS, when known.
    """

    did: str = dx.field(description="repository DID the blob was fetched from")
    cid: str = dx.field(description="content identifier of the blob")
    data: bytes = dx.field(opaque=True, description="raw blob bytes")
    mime_type: str | None = dx.field(
        default=None,
        description="MIME type reported by the PDS, when known",
    )


class BlobClient:
    """An XRPC client for streamed, content-addressed blob fetch.

    Parameters
    ----------
    endpoint : str
        The base URL of the PDS (for example ``https://pds.example``).
    client : httpx.Client or None, optional
        An injected HTTP client. When omitted, a private client is created and
        closed with this client. Public reads need no auth.
    """

    def __init__(
        self,
        endpoint: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None

    def __enter__(self) -> Self:
        """Enter the client as a context manager.

        Returns
        -------
        Self
            This client.
        """
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Close the client on context-manager exit.

        Parameters
        ----------
        _exc_type : type[BaseException] or None
            The exception type, if the block raised.
        _exc : BaseException or None
            The exception instance, if the block raised.
        _tb : types.TracebackType or None
            The traceback, if the block raised.
        """
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client if this client owns it."""
        if self._owns_client:
            self._client.close()

    def _xrpc_url(self) -> str:
        """Build the XRPC URL for ``getBlob``.

        Returns
        -------
        str
            The fully qualified XRPC query URL.
        """
        return f"{self._endpoint}/xrpc/{_GET_BLOB_NSID}"

    def get_blob(self, did: str, cid: str) -> BlobBytes:
        """Fetch blob bytes for a DID and CID, streamed.

        The response is streamed in chunks and concatenated so a large media
        blob is not materialised twice; the media layer is responsible for
        caching by CID.

        Parameters
        ----------
        did : str
            The repository DID that holds the blob.
        cid : str
            The content identifier of the blob.

        Returns
        -------
        BlobBytes
            The content-addressed blob bytes holder.

        Raises
        ------
        httpx.HTTPStatusError
            If the PDS returns a non-success status.
        """
        params = {"did": did, "cid": cid}
        with self._client.stream(
            "GET",
            self._xrpc_url(),
            params=params,
        ) as response:
            response.raise_for_status()
            mime_type = response.headers.get("content-type")
            chunks = list(response.iter_bytes(_STREAM_CHUNK_SIZE))
        return BlobBytes(
            did=did,
            cid=cid,
            data=b"".join(chunks),
            mime_type=mime_type,
        )

    def iter_blob(self, did: str, cid: str) -> Iterator[bytes]:
        """Yield blob bytes in chunks without buffering the whole blob.

        Parameters
        ----------
        did : str
            The repository DID that holds the blob.
        cid : str
            The content identifier of the blob.

        Yields
        ------
        bytes
            Successive byte chunks of the blob.

        Raises
        ------
        httpx.HTTPStatusError
            If the PDS returns a non-success status.
        """
        params = {"did": did, "cid": cid}
        with self._client.stream(
            "GET",
            self._xrpc_url(),
            params=params,
        ) as response:
            response.raise_for_status()
            yield from response.iter_bytes(_STREAM_CHUNK_SIZE)


def get_blob(endpoint: str, did: str, cid: str) -> BlobBytes:
    """Fetch blob bytes using a throwaway client.

    Parameters
    ----------
    endpoint : str
        The base URL of the PDS.
    did : str
        The repository DID that holds the blob.
    cid : str
        The content identifier of the blob.

    Returns
    -------
    BlobBytes
        The content-addressed blob bytes holder.

    Raises
    ------
    httpx.HTTPStatusError
        If the PDS returns a non-success status.
    """
    with BlobClient(endpoint) as client:
        return client.get_blob(did, cid)


def upload_blob(data: bytes, mime_type: str) -> BlobRef:
    """Upload blob bytes and return a blob reference.

    Blob upload is a write to the authenticated user's own repository and is
    owned by the authoring component, which carries the OAuth session and write
    scopes. The access layer is read-only, so this is a deferred stub.

    Parameters
    ----------
    data : bytes
        The blob bytes to upload.
    mime_type : str
        The MIME type of the blob.

    Returns
    -------
    lairs.records.blobref.BlobRef
        A reference to the uploaded blob.

    Raises
    ------
    NotImplementedError
        Always; blob upload is owned by the authoring component.
    """
    # deferred to the authoring component (write path); see plan section 6b.2.
    _ = (data, mime_type)
    msg = "blob upload is owned by the authoring component (write path)"
    raise NotImplementedError(msg)
