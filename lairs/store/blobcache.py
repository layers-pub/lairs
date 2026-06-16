"""Content-addressed blob cache.

Caches blob bytes on disk under ``blobs/<cid>``, populated lazily by the media
layer and shared across corpora. The cache is content-addressed: a blob's CID is
its file name, so identical content stored under the same CID is deduplicated and
``put`` is idempotent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["BlobCache"]

# the subdirectory under the cache root holding content-addressed blobs.
_BLOBS_DIR = "blobs"


class BlobCache:
    """A content-addressed on-disk cache of blob bytes.

    Parameters
    ----------
    root : pathlib.Path
        The cache root directory. Blobs are stored under ``root/blobs/<cid>``.

    Attributes
    ----------
    root : pathlib.Path
        The cache root directory.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _blobs_dir(self) -> Path:
        """Return the blobs directory, creating it if needed."""
        blobs = self.root / _BLOBS_DIR
        blobs.mkdir(parents=True, exist_ok=True)
        return blobs

    def path_for(self, cid: str) -> Path:
        """Return the on-disk path a blob would occupy for a CID.

        The path is returned whether or not the blob is present, so the media
        layer can stream bytes straight to it.

        Parameters
        ----------
        cid : str
            The content identifier.

        Returns
        -------
        pathlib.Path
            The path ``root/blobs/<cid>``.
        """
        return self.root / _BLOBS_DIR / cid

    def exists(self, cid: str) -> bool:
        """Return ``True`` if a blob for ``cid`` is cached.

        Parameters
        ----------
        cid : str
            The content identifier.

        Returns
        -------
        bool
            Whether the blob is present on disk.
        """
        return self.path_for(cid).is_file()

    def get(self, cid: str) -> bytes | None:
        """Return cached bytes for a CID, or ``None`` if absent.

        Parameters
        ----------
        cid : str
            The content identifier.

        Returns
        -------
        bytes or None
            The cached bytes, or ``None`` when the blob is not cached.
        """
        path = self.path_for(cid)
        if not path.is_file():
            return None
        return path.read_bytes()

    def put(self, cid: str, data: bytes) -> Path:
        """Store bytes under a CID.

        Storing the same CID again overwrites the existing file with identical
        content, so ``put`` is idempotent for content-addressed input.

        Parameters
        ----------
        cid : str
            The content identifier.
        data : bytes
            The bytes to cache.

        Returns
        -------
        pathlib.Path
            The path the bytes were written to.
        """
        path = self._blobs_dir() / cid
        path.write_bytes(data)
        return path
