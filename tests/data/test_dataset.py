"""Unit and integration tests for lairs.data.dataset."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lairs.data import dataset
from lairs.data.dataset import Dataset
from lairs.data.features import Features
from lairs.records._generated.expression import Expression

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _expr(doc_id: str) -> Expression:
    """Build a minimal expression record for tests."""
    return Expression(id=doc_id, kind="document", createdAt=_NOW, text=doc_id)


def _records(count: int) -> list[Expression]:
    """Build a list of ``count`` distinct expression records."""
    return [_expr(f"d{index}") for index in range(count)]


def test_exports() -> None:
    assert set(dataset.__all__) == {"Dataset"}


def test_len_and_getitem() -> None:
    ds: Dataset[Expression] = Dataset(_records(3))
    assert len(ds) == 3
    assert ds[0].id == "d0"
    assert ds[2].id == "d2"


def test_getitem_out_of_range() -> None:
    ds: Dataset[Expression] = Dataset(_records(1))
    with pytest.raises(IndexError):
        _ = ds[5]


def test_iter_yields_each_record() -> None:
    ds: Dataset[Expression] = Dataset(_records(3))
    assert [record.id for record in ds] == ["d0", "d1", "d2"]


def test_iter_batches() -> None:
    ds: Dataset[Expression] = Dataset(_records(5))
    batches = list(ds.iter(batch_size=2))
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert batches[0][0].id == "d0"


def test_iter_rejects_nonpositive_batch_size() -> None:
    ds: Dataset[Expression] = Dataset(_records(1))
    with pytest.raises(ValueError, match="positive"):
        list(ds.iter(batch_size=0))


def test_map_is_lazy_and_applies() -> None:
    calls: list[str] = []

    def mark(expr: Expression) -> Expression:
        calls.append(expr.id)
        return Expression(
            id=expr.id,
            kind=expr.kind,
            createdAt=expr.createdAt,
            text=expr.id.upper(),
        )

    ds: Dataset[Expression] = Dataset(_records(2))
    mapped = ds.map(mark)
    # nothing runs until the result is iterated.
    assert calls == []
    out = list(mapped)
    assert calls == ["d0", "d1"]
    assert [record.text for record in out] == ["D0", "D1"]


def test_map_takes_model_for_reshaped_output() -> None:
    ds: Dataset[Expression] = Dataset(_records(2))
    mapped = ds.map(lambda e: e, model=Expression)
    assert "id" in mapped.features.names()


def test_map_batched_receives_whole_batch() -> None:
    seen: list[int] = []

    def dedupe(batch: Sequence[Expression]) -> list[Expression]:
        seen.append(len(batch))
        # collapse each batch to a single representative record.
        return [batch[0]]

    ds: Dataset[Expression] = Dataset(_records(5))
    out = list(ds.map_batched(dedupe, batch_size=2))
    # the callable saw batches of 2, 2, 1, not individual records.
    assert seen == [2, 2, 1]
    # one record survives per batch, so the output count drops.
    assert [r.id for r in out] == ["d0", "d2", "d4"]


def test_map_batched_is_lazy() -> None:
    calls: list[int] = []

    def grow(batch: Sequence[Expression]) -> Sequence[Expression]:
        calls.append(len(batch))
        return batch

    ds: Dataset[Expression] = Dataset(_records(4))
    mapped = ds.map_batched(grow, batch_size=2)
    # nothing runs until the result is iterated.
    assert calls == []
    out = [r.id for r in mapped]
    assert out == ["d0", "d1", "d2", "d3"]
    assert calls == [2, 2]


def test_map_batched_rejects_nonpositive_batch_size() -> None:
    ds: Dataset[Expression] = Dataset(_records(1))
    with pytest.raises(ValueError, match="positive"):
        ds.map_batched(lambda batch: batch, batch_size=0)


def test_map_batched_over_streaming_source() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(5)

    ds = Dataset.streaming(source, model=Expression)
    mapped = ds.map_batched(lambda batch: batch, batch_size=2)
    assert mapped.is_streaming is True
    # the streaming transform is re-iterable through the fresh-iterator factory.
    assert [r.id for r in mapped] == ["d0", "d1", "d2", "d3", "d4"]
    assert [r.id for r in mapped] == ["d0", "d1", "d2", "d3", "d4"]


def test_filter_is_lazy() -> None:
    ds: Dataset[Expression] = Dataset(_records(4))
    kept = list(ds.filter(lambda e: e.id in {"d1", "d3"}))
    assert [r.id for r in kept] == ["d1", "d3"]


def test_filter_over_streaming_source_is_reiterable() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(4)

    ds = Dataset.streaming(source, model=Expression)
    kept = ds.filter(lambda e: e.id in {"d0", "d2"})
    assert kept.is_streaming is True
    # the fresh-iterator factory means a streaming filter is re-iterable.
    assert [r.id for r in kept] == ["d0", "d2"]
    assert [r.id for r in kept] == ["d0", "d2"]


def test_map_over_streaming_chains_with_filter() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(4)

    ds = Dataset.streaming(source, model=Expression)
    chained = ds.filter(lambda e: e.id != "d1").map(
        lambda e: Expression(
            id=e.id,
            kind=e.kind,
            createdAt=e.createdAt,
            text=e.id.upper(),
        ),
    )
    assert chained.is_streaming is True
    assert [r.text for r in chained] == ["D0", "D2", "D3"]


def test_features_from_records() -> None:
    ds: Dataset[Expression] = Dataset(_records(1))
    feats = ds.features
    assert isinstance(feats, Features)
    assert "id" in feats.names()


def test_features_for_empty_dataset_with_model() -> None:
    ds: Dataset[Expression] = Dataset(model=Expression)
    assert "id" in ds.features.names()


def test_features_for_empty_dataset_without_model_raises() -> None:
    ds: Dataset[Expression] = Dataset()
    with pytest.raises(ValueError, match="empty dataset"):
        _ = ds.features


def test_to_arrow_materializes() -> None:
    ds: Dataset[Expression] = Dataset(_records(3))
    table = ds.to_arrow()
    assert table.num_rows == 3
    assert "text" in table.column_names


def test_streaming_iterates_and_is_reiterable() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(3)

    ds = Dataset.streaming(source, model=Expression)
    assert ds.is_streaming is True
    assert [r.id for r in ds] == ["d0", "d1", "d2"]
    # a fresh iterator means the stream can be consumed again.
    assert [r.id for r in ds] == ["d0", "d1", "d2"]


def test_streaming_has_no_len_or_getitem() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(2)

    ds = Dataset.streaming(source, model=Expression)
    with pytest.raises(TypeError, match="streaming"):
        len(ds)
    with pytest.raises(TypeError, match="streaming"):
        _ = ds[0]


def test_streaming_features_use_model() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(1)

    ds = Dataset.streaming(source, model=Expression)
    assert "id" in ds.features.names()


def test_streaming_to_arrow_drains() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(2)

    ds = Dataset.streaming(source, model=Expression)
    assert ds.to_arrow().num_rows == 2


def test_take_and_materialize() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(5)

    ds = Dataset.streaming(source, model=Expression)
    taken = ds.take(2)
    assert len(taken) == 2
    assert taken[0].id == "d0"
    materialized = ds.materialize()
    assert len(materialized) == 5


def test_from_iterable() -> None:
    ds = Dataset.from_iterable(iter(_records(3)), model=Expression)
    assert len(ds) == 3


def test_records_and_source_are_mutually_exclusive() -> None:
    def source() -> Iterator[Expression]:
        yield from _records(1)

    with pytest.raises(ValueError, match="not both"):
        Dataset(_records(1), source=source)


@pytest.mark.integration
def test_to_pandas_when_available() -> None:
    pd = pytest.importorskip("pandas")
    ds: Dataset[Expression] = Dataset(_records(2))
    frame = ds.to_pandas()
    assert isinstance(frame, pd.DataFrame)
    assert len(frame) == 2
