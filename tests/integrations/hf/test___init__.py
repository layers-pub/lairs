"""Unit tests for the lairs.integrations.hf package surface."""

from __future__ import annotations

import lairs.integrations.hf as mod


def test_all_is_empty_list() -> None:
    assert mod.__all__ == []
