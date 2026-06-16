"""Unit tests for the lairs.records._generated package surface."""

from __future__ import annotations

from lairs.records import _generated


def test_all_is_empty_list() -> None:
    assert _generated.__all__ == []
