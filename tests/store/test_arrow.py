"""Unit tests for lairs.store.arrow."""

from __future__ import annotations

from pathlib import Path

import pytest

from lairs.store import arrow


def test_exports() -> None:
    assert set(arrow.__all__) == {"materialize", "records_to_table"}


def test_records_to_table_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        arrow.records_to_table([])


def test_materialize_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        arrow.materialize(Path("repo"), Path("out"))
