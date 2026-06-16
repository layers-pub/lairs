"""Unit tests for the lairs.integrations package surface."""

from __future__ import annotations

from lairs import integrations


def test_public_surface() -> None:
    assert set(integrations.__all__) == {
        "Codec",
        "Exporter",
        "KnowledgeBase",
        "Registry",
        "StorageBackend",
        "UnknownAdapterError",
        "available",
        "get_codec",
        "get_exporter",
        "get_knowledge_base",
        "register_codec",
        "register_exporter",
        "register_knowledge_base",
    }


def test_reexports_are_importable() -> None:
    assert integrations.Registry is not None
    assert callable(integrations.get_codec)
