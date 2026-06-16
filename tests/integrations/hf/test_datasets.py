"""Unit and integration tests for lairs.integrations.hf.datasets."""

from __future__ import annotations

import pytest

from lairs.integrations.hf.datasets import HuggingFaceExporter


def test_name() -> None:
    assert HuggingFaceExporter.name == "hf"


def test_export_is_a_stub() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1, 2]})
    with pytest.raises(NotImplementedError):
        HuggingFaceExporter().export(table)


@pytest.mark.integration
def test_export_live() -> None:
    pytest.importorskip("datasets")
    pytest.skip("requires a materialized arrow view")
