"""Content-addressed blob cache.

Caches blob bytes on disk under ``blobs/<cid>``, populated lazily by the media
layer and shared across corpora. The cache is content-addressed: a blob's CID is
its file name, so identical content stored under the same CID is deduplicated and
``put`` is idempotent. When the key is a decodable CID, :meth:`BlobCache.put`
verifies that it actually addresses the bytes (the multihash digest matches), so
a wrong CID can never poison the cache. A key that is not a CID (for example an
external URI used by the media layer to cache fetched bytes) is treated as an
opaque, trusted cache key and is stored without a digest check. Writes are atomic
so a crash mid-write cannot leave a truncated blob that :meth:`BlobCache.exists`
would report as present.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from multiformats import CID, multihash

__all__ = ["BlobCache", "BlobCacheError"]

# the subdirectory under the cache root holding content-addressed blobs.
_BLOBS_DIR = "blobs"


class BlobCacheError(ValueError):
    """Raised when a blob operation violates the cache's content-addressing.

    Carried by :meth:`BlobCache.put` when the key contains path separators that
    would escape the blobs directory, or when a key that is a decodable CID has a
    multihash digest that does not match the supplied bytes.
    """


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

    @staticmethod
    def _safe_cid(cid: str) -> str:
        """Return ``cid`` when it is a single safe path component, else raise.

        A CID file name must be one path component with no separators and no
        parent reference, so a hostile or malformed CID cannot escape the blobs
        directory.

        Parameters
        ----------
        cid : str
            The content identifier to validate.

        Returns
        -------
        str
            The validated CID.

        Raises
        ------
        BlobCacheError
            If the CID is empty, a parent reference, or contains a path
            separator.
        """
        if not cid or cid in (".", "..") or "/" in cid or "\\" in cid or os.sep in cid:
            msg = f"blob CID is not a safe path component: {cid!r}"
            raise BlobCacheError(msg)
        return cid

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

        Raises
        ------
        BlobCacheError
            If the CID is not a safe single path component.
        """
        return self.root / _BLOBS_DIR / self._safe_cid(cid)

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

    def _verify_cid(self, cid: str, data: bytes) -> None:
        """Raise :class:`BlobCacheError` if a CID key does not address ``data``.

        When ``cid`` is a decodable CID, the multihash digest over ``data`` is
        recomputed with the CID's own hash function and rejected on mismatch, so
        a wrong CID cannot poison the cache. A key that is not a CID (for example
        an external URI) is treated as an opaque, trusted cache key and is not
        digest-checked.

        Parameters
        ----------
        cid : str
            The cache key supplied by the caller.
        data : bytes
            The bytes the key is claimed to address.

        Raises
        ------
        BlobCacheError
            If ``cid`` is a decodable CID whose digest does not match the bytes.
        """
        try:
            decoded = CID.decode(cid)
        except ValueError, KeyError:
            # not a CID: an opaque trusted cache key (e.g. an external URI).
            return
        try:
            recomputed = multihash.digest(data, decoded.hashfun.name)
        except (ValueError, KeyError) as exc:
            msg = f"blob CID uses an unsupported hash function: {cid!r}"
            raise BlobCacheError(msg) from exc
        if recomputed != decoded.digest:
            msg = f"blob bytes do not match the supplied CID: {cid!r}"
            raise BlobCacheError(msg)

    def put(self, cid: str, data: bytes, *, verify: bool = True) -> Path:
        """Store bytes under a cache key.

        Storing the same key again overwrites the existing file with identical
        content, so ``put`` is idempotent for content-addressed input. When the
        key is a decodable CID it is verified against the bytes (its multihash
        digest must match) so a wrong CID cannot poison the cache; a non-CID key
        (for example an external URI) is stored as an opaque trusted key. The
        write is atomic (a temp file in the same directory is renamed onto the
        final path) so a crash mid-write cannot leave a truncated blob.

        Parameters
        ----------
        cid : str
            The cache key: a content identifier, or an opaque trusted key.
        data : bytes
            The bytes to cache.
        verify : bool, optional
            When ``True`` (the default), a CID key's multihash digest is checked
            against ``data`` before storing. Pass ``False`` to skip the check
            when the key has already been verified.

        Returns
        -------
        pathlib.Path
            The path the bytes were written to.

        Raises
        ------
        BlobCacheError
            If the key is not a safe path component, or (when ``verify``) is a
            decodable CID that does not address ``data``.
        """
        self._safe_cid(cid)
        if verify:
            self._verify_cid(cid, data)
        blobs = self._blobs_dir()
        path = blobs / cid
        handle, temp_name = tempfile.mkstemp(dir=blobs, prefix=f"{cid}.", suffix=".tmp")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            temp_path.replace(path)
        except OSError:
            temp_path.unlink(missing_ok=True)
            raise
        return path
