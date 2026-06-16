"""Unit and integration tests for lairs.integrations.kb.glazing."""

from __future__ import annotations

import pytest

from lairs.integrations.kb.glazing import GlazingKB


def test_name() -> None:
    assert GlazingKB.name == "glazing"


def test_resolve_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        GlazingKB().resolve("ref")


def test_search_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        GlazingKB().search("text")


def test_neighbors_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        GlazingKB().neighbors("ref")


@pytest.mark.integration
def test_resolve_live() -> None:
    pytest.importorskip("glazing")
    pytest.skip("requires network access or a local dump")
