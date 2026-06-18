"""Unit and integration tests for lairs.integrations.torch."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lairs.integrations.torch import (
    TorchExporter,
    TorchExportResult,
    TorchExportSpec,
    _numeric_column_names,
    _row_record,
    _selected_columns,
    _tensor_columns,
    collate_records,
)

if TYPE_CHECKING:
    from collections.abc import Callable

pa = pytest.importorskip("pyarrow")


def _sample_table() -> pa.Table:
    """Return a small mixed-dtype Arrow table for the pure-logic tests."""
    return pa.table(
        {
            "id": [1, 2, 3],
            "text": ["a", "b", "c"],
            "score": [0.5, 1.5, 2.5],
            "flag": [True, False, True],
        },
    )


def test_name() -> None:
    assert TorchExporter.name == "torch"


def test_importing_does_not_import_torch(
    assert_lazy_import: Callable[..., None],
) -> None:
    # importing the exporter module must never pull the optional torch extra.
    assert_lazy_import("lairs.integrations.torch", "torch")


def test_spec_defaults() -> None:
    spec = TorchExportSpec()
    assert spec.columns is None
    assert spec.tensor_columns is None
    assert spec.resolve_media is False


def test_spec_round_trip() -> None:
    spec = TorchExportSpec(
        columns=("id", "score"),
        tensor_columns=("id",),
        resolve_media=True,
    )
    assert spec.columns == ("id", "score")
    assert spec.tensor_columns == ("id",)
    assert spec.resolve_media is True


def test_numeric_column_names_excludes_strings() -> None:
    names = _numeric_column_names(_sample_table())
    assert names == ("id", "score", "flag")


def test_selected_columns_keeps_all_when_unset() -> None:
    table = _sample_table()
    assert _selected_columns(table, None) == tuple(table.column_names)
    assert _selected_columns(table, TorchExportSpec()) == tuple(table.column_names)


def test_selected_columns_honours_spec_order() -> None:
    spec = TorchExportSpec(columns=("score", "id"))
    assert _selected_columns(_sample_table(), spec) == ("score", "id")


def test_selected_columns_rejects_unknown() -> None:
    spec = TorchExportSpec(columns=("id", "missing"))
    with pytest.raises(KeyError):
        _selected_columns(_sample_table(), spec)


def test_tensor_columns_inferred_from_numeric() -> None:
    table = _sample_table()
    kept = _selected_columns(table, None)
    assert _tensor_columns(table, None, kept) == ("id", "score", "flag")


def test_tensor_columns_respects_kept_subset() -> None:
    table = _sample_table()
    spec = TorchExportSpec(columns=("text", "score"))
    kept = _selected_columns(table, spec)
    # only score is both kept and numeric.
    assert _tensor_columns(table, spec, kept) == ("score",)


def test_tensor_columns_explicit_intersected_with_kept() -> None:
    table = _sample_table()
    spec = TorchExportSpec(columns=("id", "text"), tensor_columns=("id", "score"))
    kept = _selected_columns(table, spec)
    # score is named but not kept, so it drops out.
    assert _tensor_columns(table, spec, kept) == ("id",)


def test_row_record_reads_kept_columns() -> None:
    table = _sample_table()
    row = _row_record(table, 1, ("id", "text"))
    assert row == {"id": 2, "text": "b"}


def test_row_record_out_of_range() -> None:
    with pytest.raises(IndexError):
        _row_record(_sample_table(), 99, ("id",))


def test_collate_passthrough_without_tensor_columns() -> None:
    # with no tensor columns, collation returns the per-column passthrough lists
    # without ever touching torch (its lazy-import discipline is covered by
    # test_importing_does_not_import_torch).
    batch = [{"text": "a", "id": 1}, {"text": "b", "id": 2}]
    collated = collate_records(batch, ())  # ty: ignore[invalid-argument-type]
    assert collated == {"text": ["a", "b"], "id": [1, 2]}


def test_collate_empty_batch() -> None:
    assert collate_records([], ()) == {}


# -- tests that need torch installed -----------------------------------------


def test_export_returns_result() -> None:
    pytest.importorskip("torch")
    table = _sample_table()
    result = TorchExporter().export(table)
    assert isinstance(result, TorchExportResult)
    assert result.tensor_columns == ("id", "score", "flag")
    assert result.resolve_media is False


def test_export_map_dataset_indexing() -> None:
    pytest.importorskip("torch")
    table = _sample_table()
    result = TorchExporter().export(table)
    # torch's base Dataset stub does not declare __len__ (map-style subclasses
    # add it), so len() over the concrete dataset is invisible to the checker.
    assert len(result.dataset) == 3  # ty: ignore[invalid-argument-type]
    assert result.dataset[0]["id"] == 1
    assert result.dataset[2]["text"] == "c"


def test_export_iterable_dataset_streams() -> None:
    pytest.importorskip("torch")
    table = _sample_table()
    result = TorchExporter().export(table)
    rows = list(result.iterable)
    assert len(rows) == 3
    assert [row["id"] for row in rows] == [1, 2, 3]


def test_export_collate_stacks_tensor_columns() -> None:
    torch = pytest.importorskip("torch")
    table = _sample_table()
    result = TorchExporter().export(table, spec=TorchExportSpec(tensor_columns=("id",)))
    batch = [result.dataset[0], result.dataset[1]]
    collated = result.collate(batch)
    assert torch.is_tensor(collated["id"])
    assert collated["id"].tolist() == [1, 2]  # ty: ignore[unresolved-attribute]
    # non-tensor columns stay as per-row lists.
    assert collated["text"] == ["a", "b"]


def test_export_records_resolve_media_intent() -> None:
    pytest.importorskip("torch")
    table = _sample_table()
    spec = TorchExportSpec(resolve_media=True)
    result = TorchExporter().export(table, spec=spec)
    assert result.resolve_media is True


def test_export_rejects_unknown_column() -> None:
    pytest.importorskip("torch")
    table = _sample_table()
    with pytest.raises(KeyError):
        TorchExporter().export(table, spec=TorchExportSpec(columns=("nope",)))


@pytest.mark.integration
def test_export_dataloader_round_trip() -> None:
    torch = pytest.importorskip("torch")
    data_loader_cls = torch.utils.data.DataLoader

    table = _sample_table()
    result = TorchExporter().export(table, spec=TorchExportSpec(tensor_columns=("id",)))
    loader = data_loader_cls(
        result.dataset,
        batch_size=2,
        collate_fn=result.collate,
    )
    batches = list(loader)
    assert len(batches) == 2
    assert torch.is_tensor(batches[0]["id"])
    assert batches[0]["id"].tolist() == [1, 2]
