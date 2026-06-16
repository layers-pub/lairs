"""Unit tests for the lairs.store package surface."""

from __future__ import annotations

import lairs.store as mod


def test_all_is_empty_list() -> None:
    assert mod.__all__ == []
