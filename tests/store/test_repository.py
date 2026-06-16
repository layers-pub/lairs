"""Unit tests for lairs.store.repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from lairs.store import repository


def test_exports() -> None:
    assert set(repository.__all__) == {"Repository"}


def test_commit_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        repository.Repository(Path("repo")).commit("msg")


def test_tag_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        repository.Repository(Path("repo")).tag("v1")


def test_diff_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        repository.Repository(Path("repo")).diff("a", "b")
