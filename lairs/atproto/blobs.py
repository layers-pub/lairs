"""Blob fetch and upload over ATProto.

Wraps ``com.atproto.sync.getBlob`` for streamed, CID-cached media bytes and
``com.atproto.repo.uploadBlob`` for blob-first publishing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lairs.records.blobref import BlobRef

__all__ = ["get_blob", "upload_blob"]


def get_blob(did: str, cid: str) -> bytes:
    """Fetch blob bytes for a DID and CID.

    Parameters
    ----------
    did : str
        The repository DID that holds the blob.
    cid : str
        The content identifier of the blob.

    Returns
    -------
    bytes
        The blob bytes.

    Raises
    ------
    NotImplementedError
        Always, until the access layer lands.
    """
    raise NotImplementedError


def upload_blob(data: bytes, mime_type: str) -> BlobRef:
    """Upload blob bytes and return a blob reference.

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
        Always, until the access layer lands.
    """
    raise NotImplementedError
