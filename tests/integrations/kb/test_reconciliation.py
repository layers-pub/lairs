"""Unit and integration tests for lairs.integrations.kb.reconciliation."""

from __future__ import annotations

import pytest

from lairs.integrations.kb.reconciliation import ReconciliationKB


def test_name() -> None:
    assert ReconciliationKB.name == "reconciliation"


def test_resolve_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        ReconciliationKB("https://recon.example").resolve("ref")


def test_search_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        ReconciliationKB("https://recon.example").search("text")


def test_neighbors_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        ReconciliationKB("https://recon.example").neighbors("ref")


@pytest.mark.integration
def test_resolve_live() -> None:
    pytest.skip("requires network access or a local dump")
