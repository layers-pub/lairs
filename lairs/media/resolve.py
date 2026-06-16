"""Media resolution: a media record resolves to a decoded handle.

``resolve_media`` dispatches on blob versus external URI, fetches lazily, and
caches by content identifier. The returned ``MediaHandle`` is a didactic model
that carries the raw bytes in an opaque field with typed metadata alongside.

The transport (blob fetch) and the on-disk cache are owned by other components,
so they are injected through the small ``BlobFetcher`` and ``BlobCache``
protocols rather than implemented here; an HTTP fetcher for ``externalUri`` is
likewise injected. When no fetcher is supplied the handle is returned with
typed metadata only and bytes are left empty for a later decode.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import didactic.api as dx

__all__ = [
    "BlobCache",
    "BlobFetcher",
    "MediaHandle",
    "UriFetcher",
    "resolve_media",
]


@runtime_checkable
class BlobFetcher(Protocol):
    """A port that fetches blob bytes for a repository by content identifier.

    Component B (the ATProto client) supplies a concrete implementation; the
    media layer only depends on this shape.
    """

    def get_blob(self, did: str, cid: str) -> bytes:
        """Return the bytes of a blob.

        Parameters
        ----------
        did : str
            The DID of the repository holding the blob.
        cid : str
            The content identifier of the blob.

        Returns
        -------
        bytes
            The blob bytes.
        """
        ...


@runtime_checkable
class UriFetcher(Protocol):
    """A port that fetches bytes for an externally hosted media URI."""

    def get_uri(self, uri: str) -> bytes:
        """Return the bytes of an external resource.

        Parameters
        ----------
        uri : str
            The URI of the external resource.

        Returns
        -------
        bytes
            The fetched bytes.
        """
        ...


@runtime_checkable
class BlobCache(Protocol):
    """A content-addressed cache port for resolved bytes.

    Component C (the store) supplies a concrete implementation; the media layer
    only depends on this shape.
    """

    def exists(self, cid: str) -> bool:
        """Return whether a content identifier is cached.

        Parameters
        ----------
        cid : str
            The content identifier to check.

        Returns
        -------
        bool
            ``True`` if the bytes are cached.
        """
        ...

    def get(self, cid: str) -> bytes:
        """Return cached bytes for a content identifier.

        Parameters
        ----------
        cid : str
            The content identifier to read.

        Returns
        -------
        bytes
            The cached bytes.
        """
        ...

    def put(self, cid: str, data: bytes) -> None:
        """Store bytes under a content identifier.

        Parameters
        ----------
        cid : str
            The content identifier to write under.
        data : bytes
            The bytes to store.
        """
        ...


class MediaHandle(dx.Model):
    """A resolved media handle holding raw bytes and typed metadata.

    The raw media bytes live in an opaque field; the modality, MIME type, and
    duration are typed metadata so callers never inspect the payload blindly.
    When ``data`` is empty the handle is metadata-only and bytes are fetched on
    a later decode.

    Parameters
    ----------
    cid : str
        The content identifier of the resolved media.
    mime_type : str
        The MIME type of the media.
    modality : str
        The modality (``audio``, ``video``, ``image``, or ``document``).
    duration_ms : int or None, optional
        The media duration in milliseconds, when known.
    external_uri : str or None, optional
        The external URI, when the media is externally hosted.
    data : bytes, optional
        The raw media bytes, carried as an opaque payload.
    """

    cid: str = dx.field(description="content identifier of the media")
    mime_type: str = dx.field(description="MIME type of the media")
    modality: str = dx.field(description="media modality token")
    duration_ms: int | None = dx.field(
        default=None,
        description="media duration in milliseconds, when known",
    )
    external_uri: str | None = dx.field(
        default=None,
        description="external URI, when the media is externally hosted",
    )
    data: bytes = dx.field(
        default=b"",
        opaque=True,
        description="raw media bytes carried as an opaque payload",
    )


def _str_attr(model: dx.Model, *names: str) -> str | None:
    """Return the first present str-valued attribute among ``names``."""
    for name in names:
        value = getattr(model, name, None)
        if isinstance(value, str):
            return value
    return None


def _int_attr(model: dx.Model, *names: str) -> int | None:
    """Return the first present int-valued attribute among ``names``."""
    for name in names:
        value = getattr(model, name, None)
        # bool is an int subclass; exclude it so flags never read as offsets
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _blob_ref(model: dx.Model) -> dx.Model | None:
    """Return the blob reference sub-model of a media record, if any."""
    blob = getattr(model, "blob", None)
    if isinstance(blob, dx.Model):
        return blob
    return None


def resolve_media(
    media: dx.Model,
    *,
    did: str | None = None,
    blob_fetcher: BlobFetcher | None = None,
    uri_fetcher: UriFetcher | None = None,
    cache: BlobCache | None = None,
) -> MediaHandle:
    """Resolve a media record to a media handle, fetching bytes lazily.

    Dispatches on whether the record carries a ``blob`` or an ``externalUri``.
    A cached payload is returned directly; otherwise, when a matching fetcher is
    supplied, the bytes are fetched and cached. With no fetcher the handle is
    metadata-only (empty ``data``) so callers can decide when to fetch.

    Parameters
    ----------
    media : didactic.Model
        A ``media.media`` record instance.
    did : str or None, optional
        The DID of the repository holding the blob, required to fetch a blob.
    blob_fetcher : BlobFetcher or None, optional
        The injected blob transport (Component B).
    uri_fetcher : UriFetcher or None, optional
        The injected external-URI transport.
    cache : BlobCache or None, optional
        The injected content-addressed cache (Component C).

    Returns
    -------
    MediaHandle
        The resolved handle, with bytes populated when a fetch succeeded.

    Raises
    ------
    ValueError
        If the record carries neither a blob nor an external URI.
    """
    modality = _str_attr(media, "kind", "modality") or "document"
    mime_type = _str_attr(media, "mime_type", "mimeType") or "application/octet-stream"
    duration_ms = _int_attr(media, "duration_ms", "durationMs")
    external_uri = _str_attr(media, "external_uri", "externalUri")
    blob = _blob_ref(media)

    if blob is not None:
        cid = _str_attr(blob, "cid") or ""
        blob_mime = _str_attr(blob, "mime_type", "mimeType")
        if blob_mime is not None:
            mime_type = blob_mime
        data = _fetch_blob(cid, did=did, blob_fetcher=blob_fetcher, cache=cache)
        return MediaHandle(
            cid=cid,
            mime_type=mime_type,
            modality=modality,
            duration_ms=duration_ms,
            data=data,
        )

    if external_uri is not None:
        data = _fetch_uri(external_uri, uri_fetcher=uri_fetcher, cache=cache)
        return MediaHandle(
            cid=external_uri,
            mime_type=mime_type,
            modality=modality,
            duration_ms=duration_ms,
            external_uri=external_uri,
            data=data,
        )

    msg = "media record carries neither a blob nor an externalUri"
    raise ValueError(msg)


def _fetch_blob(
    cid: str,
    *,
    did: str | None,
    blob_fetcher: BlobFetcher | None,
    cache: BlobCache | None,
) -> bytes:
    """Fetch and cache blob bytes, returning empty when no fetcher is given."""
    if cache is not None and cid and cache.exists(cid):
        return cache.get(cid)
    if blob_fetcher is None or did is None or not cid:
        return b""
    data = blob_fetcher.get_blob(did, cid)
    if cache is not None:
        cache.put(cid, data)
    return data


def _fetch_uri(
    uri: str,
    *,
    uri_fetcher: UriFetcher | None,
    cache: BlobCache | None,
) -> bytes:
    """Fetch and cache external bytes, returning empty when no fetcher is given."""
    if cache is not None and cache.exists(uri):
        return cache.get(uri)
    if uri_fetcher is None:
        return b""
    data = uri_fetcher.get_uri(uri)
    if cache is not None:
        cache.put(uri, data)
    return data
