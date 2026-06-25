"""Unit tests for lairs.records.views."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import didactic.api as dx

from lairs.records import views
from lairs.records._generated import annotation, defs


def _token_anchor(index: int) -> defs.Anchor:
    return defs.Anchor(
        tokenRef=defs.TokenRef(tokenizationId=defs.Uuid(value="t"), tokenIndex=index),
    )


def _span_anchor(start: int, end: int) -> defs.Anchor:
    return defs.Anchor(textSpan=defs.Span(byteStart=start, byteEnd=end))


def _layer() -> annotation.AnnotationLayer:
    return annotation.AnnotationLayer(
        kind="token-tag",
        subkind="pos",
        expression="at://did:plc:x/pub.layers.expression.expression/r",
        createdAt=datetime(2020, 1, 1, tzinfo=UTC),
        annotations=(
            annotation.Annotation(
                uuid=defs.Uuid(value="u1"),
                label="NOUN",
                anchor=_token_anchor(0),
            ),
            annotation.Annotation(
                uuid=defs.Uuid(value="u2"),
                label="VERB",
                anchor=_span_anchor(0, 3),
            ),
        ),
    )


def test_exports() -> None:
    assert set(views.__all__) == {"anchor_kind", "explode_layer"}


def test_anchor_kind_token_ref() -> None:
    assert views.anchor_kind(_token_anchor(2)) == "tokenRef"


def test_anchor_kind_text_span() -> None:
    assert views.anchor_kind(_span_anchor(0, 4)) == "textSpan"


def test_anchor_kind_temporal_span() -> None:
    anchor = defs.Anchor(temporalSpan=defs.TemporalSpan(start=0, ending=10))
    assert views.anchor_kind(anchor) == "temporalSpan"


def test_anchor_kind_none_when_empty() -> None:
    assert views.anchor_kind(defs.Anchor()) == "none"


def test_explode_layer_yields_one_row_per_annotation() -> None:
    rows = list(views.explode_layer(_layer()))
    assert len(rows) == 2


def test_explode_layer_row_shape() -> None:
    rows = list(views.explode_layer(_layer()))
    first, second = rows
    assert first["annotation_index"] == 0
    assert first["layer_kind"] == "token-tag"
    assert first["layer_subkind"] == "pos"
    assert first["anchor_kind"] == "tokenRef"
    assert first["label"] == "NOUN"
    assert second["annotation_index"] == 1
    assert second["anchor_kind"] == "textSpan"
    assert second["label"] == "VERB"


def test_explode_layer_rows_are_json_valued() -> None:
    rows = list(views.explode_layer(_layer()))
    # the rows serialise without custom encoders, confirming they are json-shaped
    assert json.loads(json.dumps(rows)) == rows


def test_anchor_kind_none_for_non_mapping_row() -> None:
    assert views._anchor_kind_of_row("not a mapping") == "none"


def test_anchor_kind_falls_back_to_unknown_property() -> None:
    # an anchor row that sets only a property outside the known anchor set
    # still names a kind via the tolerant sorted-keys fallback
    row = {"futureKind": {"value": 1}, "zlast": None}
    assert views._anchor_kind_of_row(row) == "futureKind"


def test_anchor_kind_known_property_wins_over_fallback() -> None:
    row = {"futureKind": {"value": 1}, "textSpan": {"byteStart": 0, "byteEnd": 1}}
    assert views._anchor_kind_of_row(row) == "textSpan"


class _LayerWithoutAnnotations(dx.Model):
    """A layer-shaped model whose annotations field is absent."""

    kind: str = dx.field(description="the layer kind")


class _LayerWithScalarAnnotations(dx.Model):
    """A layer-shaped model whose annotations field is not a list."""

    annotations: str = dx.field(description="a non-list annotations value")


class _LayerWithScalarEntries(dx.Model):
    """A layer-shaped model whose annotations entries are non-dict scalars."""

    annotations: tuple[int, ...] = dx.field(
        default_factory=tuple,
        description="non-dict annotation entries",
    )


def test_explode_layer_yields_nothing_when_annotations_absent() -> None:
    layer = _LayerWithoutAnnotations(kind="token-tag")
    assert list(views.explode_layer(layer)) == []


def test_explode_layer_yields_nothing_when_annotations_not_a_list() -> None:
    layer = _LayerWithScalarAnnotations(annotations="oops")
    assert list(views.explode_layer(layer)) == []


def test_explode_layer_skips_non_dict_annotation_entries() -> None:
    # entries that dump to non-dict scalars are skipped by the per-entry guard
    layer = _LayerWithScalarEntries(annotations=(1, 2, 3))
    assert list(views.explode_layer(layer)) == []
