"""Content-addressed blob cache.

Caches blob bytes on disk under ``blobs/<cid>``, populated lazily by the media
layer and shared across corpora.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["BlobCache"]


class BlobCache:
    """A content-addressed on-disk cache of blob bytes.

    Parameters
    ----------
    root : pathlib.Path
        The cache root directory.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, cid: str) -> bytes | None:
        """Return cached bytes for a CID, or ``None`` if absent.

        Parameters
        ----------
        cid : str
            The content identifier.

        Returns
        -------
        bytes or None
            The cached bytes, if present.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError

    def put(self, cid: str, data: bytes) -> None:
        """Store bytes under a CID.

        Parameters
        ----------
        cid : str
            The content identifier.
        data : bytes
            The bytes to cache.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError
