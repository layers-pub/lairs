"""Unit and integration tests for lairs.integrations.tfdata."""

from __future__ import annotations

import pytest

from lairs.integrations.tfdata import TfDataExporter


def test_name() -> None:
    assert TfDataExporter.name == "tfdata"


def test_export_is_a_stub() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1, 2]})
    with pytest.raises(NotImplementedError):
        TfDataExporter().export(table)


@pytest.mark.integration
def test_export_live() -> None:
    pytest.importorskip("tensorflow")
    pytest.skip("requires a materialized arrow view")
