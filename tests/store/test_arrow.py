"""Unit and integration tests for lairs.store.arrow."""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx
import pyarrow.parquet as pq
import pytest

from lairs.store import arrow
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path


class _Span(dx.Model):
    """A throwaway byte-span anchor."""

    byteStart: int  # noqa: N815
    byteEnd: int  # noqa: N815


class _Expression(dx.Model):
    """A throwaway expression carrying an optional span anchor."""

    text: str
    anchor: _Span | None = None


class _Annotation(dx.Model):
    """A throwaway annotation carrying a label and an anchor."""

    label: str
    anchor: _Span | None = None


class _Layer(dx.Model):
    """A throwaway annotation layer holding annotations to explode."""

    name: str
    annotations: tuple[_Annotation, ...] = dx.field(default_factory=tuple)


_EXPR_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"
_LAYER_URI = "at://did:plc:abc/pub.layers.annotation.annotationLayer/l1"


def test_exports() -> None:
    assert set(arrow.__all__) == {
        "ANCHOR_COLUMNS",
        "RecordLike",
        "annotations_table",
        "expressions_table",
        "flatten_anchor",
        "materialize",
        "records_to_table",
    }


def test_flatten_span_anchor() -> None:
    columns = arrow.flatten_anchor({"byteStart": 3, "byteEnd": 7})
    assert columns["anchor_kind"] == "span"
    assert columns["byte_start"] == 3
    assert columns["byte_end"] == 7
    assert columns["token_id"] is None


def test_flatten_token_ref_anchor() -> None:
    columns = arrow.flatten_anchor({"tokenizationId": "tok", "tokenIndex": 4})
    assert columns["anchor_kind"] == "tokenRef"
    assert columns["token_id"] == "tok"  # noqa: S105
    assert columns["token_index"] == 4


def test_flatten_temporal_span_anchor() -> None:
    columns = arrow.flatten_anchor({"start": 100, "ending": 250})
    assert columns["anchor_kind"] == "temporalSpan"
    assert columns["t_start_ms"] == 100
    assert columns["t_end_ms"] == 250


def test_flatten_bounding_box_anchor() -> None:
    columns = arrow.flatten_anchor({"x": 1, "y": 2, "w": 3, "h": 4})
    assert columns["anchor_kind"] == "boundingBox"
    assert columns["bbox_x"] == 1
    assert columns["bbox_y"] == 2
    assert columns["bbox_w"] == 3
    assert columns["bbox_h"] == 4


def test_flatten_spatio_temporal_anchor() -> None:
    columns = arrow.flatten_anchor(
        {"temporalSpan": {"start": 10, "ending": 20}, "keyframe": []},
    )
    assert columns["anchor_kind"] == "spatioTemporalAnchor"
    assert columns["t_start_ms"] == 10
    assert columns["t_end_ms"] == 20


def test_flatten_none_anchor_is_all_unset() -> None:
    columns = arrow.flatten_anchor(None)
    assert set(columns) == set(arrow.ANCHOR_COLUMNS)
    assert all(value is None for value in columns.values())


def test_flatten_unwraps_tagged_union_wrapper() -> None:
    columns = arrow.flatten_anchor({"span": {"byteStart": 0, "byteEnd": 5}})
    assert columns["anchor_kind"] == "span"
    assert columns["byte_start"] == 0
    assert columns["byte_end"] == 5


def test_records_to_table_row_count_matches_records() -> None:
    records = [
        _Expression(text="a", anchor=_Span(byteStart=0, byteEnd=1)),
        _Expression(text="b"),
    ]
    table = arrow.records_to_table(records)
    assert table.num_rows == len(records)
    assert "anchor_kind" in table.column_names
    assert "text" in table.column_names
    kinds = table.column("anchor_kind").to_pylist()
    assert kinds == ["span", None]


def test_expressions_table_one_row_per_expression() -> None:
    records = [_Expression(text="a"), _Expression(text="b"), _Expression(text="c")]
    table = arrow.expressions_table(records)
    assert table.num_rows == 3
    assert table.column("text").to_pylist() == ["a", "b", "c"]


def test_annotations_table_explodes_layers() -> None:
    layer_a = _Layer(
        name="pos",
        annotations=(
            _Annotation(label="NOUN", anchor=_Span(byteStart=0, byteEnd=3)),
            _Annotation(label="VERB", anchor=_Span(byteStart=4, byteEnd=8)),
        ),
    )
    layer_b = _Layer(name="ner", annotations=(_Annotation(label="PER"),))
    table = arrow.annotations_table(
        [(_LAYER_URI, layer_a), (_LAYER_URI + "2", layer_b)],
    )
    # row count equals the total number of exploded annotations.
    assert table.num_rows == 3
    assert table.column("annotation_index").to_pylist() == [0, 1, 0]
    assert table.column("label").to_pylist() == ["NOUN", "VERB", "PER"]
    assert table.column("byte_start").to_pylist() == [0, 4, None]


def test_annotations_table_empty_for_layers_without_annotations() -> None:
    layer = _Layer(name="empty")
    table = arrow.annotations_table([(_LAYER_URI, layer)])
    assert table.num_rows == 0


def test_records_to_table_empty_input() -> None:
    table = arrow.records_to_table([])
    assert table.num_rows == 0


@pytest.mark.integration
def test_materialize_writes_parquet_views(tmp_path: Path) -> None:
    table = arrow.expressions_table([_Expression(text="x")])
    out_dir = tmp_path / "views"
    written = arrow.materialize(
        Repository.init(tmp_path / "repo"),
        out_dir,
        views={"expressions": table},
    )
    assert written == [out_dir / "expressions.parquet"]
    reloaded = pq.read_table(out_dir / "expressions.parquet")
    assert reloaded.num_rows == 1


@pytest.mark.integration
def test_materialize_derives_views_from_repo(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expression(text="hi", anchor=_Span(byteStart=1, byteEnd=2)))
    out_dir = tmp_path / "views"
    written = arrow.materialize(repo, out_dir)
    assert len(written) == 1
    reloaded = pq.read_table(written[0])
    assert reloaded.num_rows == 1
    assert reloaded.column("anchor_kind").to_pylist() == ["span"]
    assert reloaded.column("uri").to_pylist() == [_EXPR_URI]
