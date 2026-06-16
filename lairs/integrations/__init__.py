"""Integration adapter framework: registry, ports, and optional adapters.

Integrations are never in core; each is an optional, entry-point-discovered
extra bound to the stable ports. This package
re-exports the ports and registry helpers; the optional adapters live in
subpackages and are only importable when their extra is installed.
"""

from __future__ import annotations

from lairs.integrations.ports import (
    Codec,
    Exporter,
    KnowledgeBase,
    StorageBackend,
)
from lairs.integrations.registry import (
    Registry,
    UnknownAdapterError,
    available,
    get_codec,
    get_exporter,
    get_knowledge_base,
    register_codec,
    register_exporter,
    register_knowledge_base,
)

__all__ = [
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
]
