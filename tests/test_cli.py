"""Unit tests for lairs.cli."""

from __future__ import annotations

import pytest

from lairs import cli


def test_exports() -> None:
    assert set(cli.__all__) == {"main"}


def test_main_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        cli.main([])
