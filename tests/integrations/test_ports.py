"""Unit tests for lairs.integrations.ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.integrations import ports

if TYPE_CHECKING:
    from collections.abc import Iterable


def test_exports() -> None:
    assert set(ports.__all__) == {
        "Codec",
        "Exporter",
        "KnowledgeBase",
        "StorageBackend",
    }


def test_storage_backend_runtime_checkable() -> None:
    class FakeBackend:
        name = "fake"

        def read_bytes(self, key: str) -> bytes:
            return key.encode()

        def write_bytes(self, key: str, data: bytes) -> None:
            del key, data

        def exists(self, key: str) -> bool:
            return bool(key)

    assert isinstance(FakeBackend(), ports.StorageBackend)


def test_codec_runtime_checkable() -> None:
    class FakeCodec:
        name = "fake"

        def decode(self, src: str | bytes, *, into: str | None = None) -> str:
            del into
            return str(src)

        def encode(self, records: Iterable[str]) -> str:
            return "".join(records)

    assert isinstance(FakeCodec(), ports.Codec)


def test_non_conforming_value_is_not_a_codec() -> None:
    class NotACodec:
        name = "nope"

    assert not isinstance(NotACodec(), ports.Codec)
