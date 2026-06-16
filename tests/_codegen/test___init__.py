"""Unit tests for the lairs._codegen package surface."""

from __future__ import annotations

import lairs._codegen as mod


def test_all_is_empty_list() -> None:
    assert mod.__all__ == []
