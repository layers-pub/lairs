"""Unit and integration tests for lairs.integrations.hf.hub."""

from __future__ import annotations

import pytest

from lairs.integrations.hf import hub


def test_exports() -> None:
    assert set(hub.__all__) == {"load_from_hub", "push_to_hub"}


def test_push_to_hub_is_a_stub() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1]})
    with pytest.raises(NotImplementedError):
        hub.push_to_hub(table, "org/corpus")


def test_load_from_hub_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        hub.load_from_hub("org/corpus")


@pytest.mark.integration
def test_push_to_hub_live() -> None:
    pytest.importorskip("huggingface_hub")
    pytest.skip("requires Hub credentials")
