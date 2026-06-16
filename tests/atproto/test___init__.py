"""Unit tests for the lairs.atproto package surface."""

from __future__ import annotations

import lairs.atproto as mod


def test_all_is_empty_list() -> None:
    assert mod.__all__ == []
