"""Unit and integration tests for lairs.integrations.webdataset."""

from __future__ import annotations

import pytest

from lairs.integrations.webdataset import WebDatasetExporter


def test_name() -> None:
    assert WebDatasetExporter.name == "webdataset"


def test_export_is_a_stub() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1, 2]})
    with pytest.raises(NotImplementedError):
        WebDatasetExporter().export(table)


@pytest.mark.integration
def test_export_live() -> None:
    pytest.importorskip("webdataset")
    pytest.skip("requires a materialized arrow view")
