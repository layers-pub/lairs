"""Unit tests for lairs.media.resolve."""

from __future__ import annotations

import didactic.api as dx
import pytest

from lairs.media import resolve
from lairs.media.resolve import BlobCache, BlobFetcher, MediaHandle, UriFetcher
from lairs.records.blobref import BlobRef


class _Media(dx.Model):
    """A structural stand-in for a generated ``media.media`` record."""

    kind: str = dx.field(description="media kind slug")
    blob: BlobRef | None = dx.field(default=None, description="blob reference")
    external_uri: str | None = dx.field(default=None, description="external uri")
    mime_type: str | None = dx.field(default=None, description="mime type")
    duration_ms: int | None = dx.field(default=None, description="duration")


class _FakeFetcher:
    """A blob fetcher that records its calls and returns canned bytes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_blob(self, did: str, cid: str) -> bytes:
        self.calls.append((did, cid))
        return b"BLOBBYTES"


class _FakeUriFetcher:
    """A URI fetcher that returns canned bytes."""

    def get_uri(self, uri: str) -> bytes:  # noqa: ARG002
        return b"HTTPBYTES"


class _FakeCache:
    """An in-memory content-addressed cache for tests."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def exists(self, cid: str) -> bool:
        return cid in self.store

    def get(self, cid: str) -> bytes:
        return self.store[cid]

    def put(self, cid: str, data: bytes) -> None:
        self.store[cid] = data


def test_exports() -> None:
    assert set(resolve.__all__) == {
        "BlobCache",
        "BlobFetcher",
        "MediaHandle",
        "UriFetcher",
        "resolve_media",
    }


def test_media_handle_construction() -> None:
    handle = MediaHandle(cid="bafy", mime_type="audio/wav", modality="audio")
    assert handle.cid == "bafy"
    assert handle.modality == "audio"
    assert handle.duration_ms is None
    assert handle.data == b""


def test_protocol_conformance() -> None:
    assert isinstance(_FakeFetcher(), BlobFetcher)
    assert isinstance(_FakeUriFetcher(), UriFetcher)
    assert isinstance(_FakeCache(), BlobCache)


def test_resolve_blob_fetches_and_caches() -> None:
    fetcher = _FakeFetcher()
    cache = _FakeCache()
    media = _Media(
        kind="audio",
        blob=BlobRef(cid="bafy1", mime_type="audio/wav"),
        duration_ms=1234,
    )
    handle = resolve.resolve_media(
        media, did="did:plc:x", blob_fetcher=fetcher, cache=cache
    )
    assert handle.cid == "bafy1"
    assert handle.mime_type == "audio/wav"
    assert handle.modality == "audio"
    assert handle.duration_ms == 1234
    assert handle.data == b"BLOBBYTES"
    assert cache.store == {"bafy1": b"BLOBBYTES"}


def test_resolve_blob_uses_cache_on_second_call() -> None:
    fetcher = _FakeFetcher()
    cache = _FakeCache()
    media = _Media(kind="audio", blob=BlobRef(cid="bafy1"))
    resolve.resolve_media(media, did="did:plc:x", blob_fetcher=fetcher, cache=cache)
    resolve.resolve_media(media, did="did:plc:x", blob_fetcher=fetcher, cache=cache)
    assert fetcher.calls == [("did:plc:x", "bafy1")]


def test_resolve_external_uri() -> None:
    media = _Media(kind="video", external_uri="https://x/v.mp4", mime_type="video/mp4")
    handle = resolve.resolve_media(media, uri_fetcher=_FakeUriFetcher())
    assert handle.external_uri == "https://x/v.mp4"
    assert handle.cid == "https://x/v.mp4"
    assert handle.data == b"HTTPBYTES"


def test_resolve_metadata_only_when_no_fetcher() -> None:
    media = _Media(kind="audio", blob=BlobRef(cid="bafy1"), duration_ms=500)
    handle = resolve.resolve_media(media)
    assert handle.cid == "bafy1"
    assert handle.duration_ms == 500
    assert handle.data == b""


def test_resolve_without_blob_or_uri_raises() -> None:
    with pytest.raises(ValueError, match="neither a blob nor an externalUri"):
        resolve.resolve_media(_Media(kind="audio"))
