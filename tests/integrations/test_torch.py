"""Unit and integration tests for lairs.integrations.torch."""

from __future__ import annotations

import pytest

from lairs.integrations.torch import TorchExporter


def test_name() -> None:
    assert TorchExporter.name == "torch"


def test_export_is_a_stub() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1, 2]})
    with pytest.raises(NotImplementedError):
        TorchExporter().export(table)


@pytest.mark.integration
def test_export_live() -> None:
    pytest.importorskip("torch")
    pytest.skip("requires a materialized arrow view")
