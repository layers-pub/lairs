"""Unit tests for the lairs.author package surface."""

from __future__ import annotations

import lairs.author as mod


def test_all_is_empty_list() -> None:
    assert mod.__all__ == []
