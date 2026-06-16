"""Shared type aliases and type variables for lairs.

This module defines the small set of cross-cutting typing primitives that the
rest of lairs reuses, most importantly the recursive ``JsonValue`` alias used
for JSON-shaped data such as lexicon documents and XRPC payloads. Nothing in
lairs ever annotates with ``Any`` or ``object``; polymorphism is expressed
through these aliases, concrete unions, generics, and protocols.
"""

from __future__ import annotations

from typing import TypeVar

__all__ = [
    "JsonValue",
    "T",
    "T_co",
    "T_contra",
]

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
"""A recursive alias for any JSON-serialisable value.

This is the single shared shape for JSON documents (lexicons) and XRPC request
and response payloads. It is used in place of ``Any`` wherever lairs handles
arbitrary-but-JSON-shaped data.
"""

T = TypeVar("T")
"""An invariant type variable for generic helpers."""

T_co = TypeVar("T_co", covariant=True)
"""A covariant type variable for producer-shaped generics (for example exporters)."""

T_contra = TypeVar("T_contra", contravariant=True)
"""A contravariant type variable for consumer-shaped generics."""
