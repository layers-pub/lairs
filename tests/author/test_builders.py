"""Unit tests for lairs.author.builders."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lairs.author import builders
from lairs.records._generated.defs import (
    Anchor,
    BoundingBox,
    Keyframe,
    Span,
    SpatioTemporalAnchor,
    TemporalSpan,
    TokenRef,
)
from lairs.records._generated.expression import Expression


def test_exports() -> None:
    assert set(builders.__all__) == {
        "BuildError",
        "LayerBuilder",
        "PendingId",
        "bbox",
        "keyframe",
        "new_uuid",
        "reference",
        "span",
        "spatio_temporal",
        "temporal",
        "token_ref",
    }


# anchor builders ----------------------------------------------------------


def test_span_sets_text_span_property_only() -> None:
    anchor = builders.span(0, 4)
    assert isinstance(anchor, Anchor)
    assert isinstance(anchor.textSpan, Span)
    assert anchor.textSpan.byteStart == 0
    assert anchor.textSpan.byteEnd == 4
    assert anchor.tokenRef is None
    assert anchor.temporalSpan is None


def test_span_carries_optional_char_offsets() -> None:
    anchor = builders.span(0, 8, char_start=0, char_end=6)
    assert anchor.textSpan is not None
    assert anchor.textSpan.byteStart == 0
    assert anchor.textSpan.byteEnd == 8
    assert anchor.textSpan.charStart == 0
    assert anchor.textSpan.charEnd == 6


def test_span_leaves_char_offsets_unset_by_default() -> None:
    anchor = builders.span(0, 4)
    assert anchor.textSpan is not None
    assert anchor.textSpan.charStart is None
    assert anchor.textSpan.charEnd is None


def test_span_rejects_one_sided_char_offsets() -> None:
    with pytest.raises(builders.BuildError):
        builders.span(0, 4, char_start=0)
    with pytest.raises(builders.BuildError):
        builders.span(0, 4, char_end=4)


def test_span_rejects_inverted_char_span() -> None:
    with pytest.raises(builders.BuildError):
        builders.span(0, 8, char_start=6, char_end=2)


def test_span_rejects_negative_char_offset() -> None:
    with pytest.raises(builders.BuildError):
        builders.span(0, 8, char_start=-1, char_end=2)


def test_span_rejects_negative_offset() -> None:
    with pytest.raises(builders.BuildError):
        builders.span(-1, 4)


def test_span_rejects_inverted_span() -> None:
    with pytest.raises(builders.BuildError):
        builders.span(5, 2)


def test_token_ref_wraps_tokenization_uuid() -> None:
    anchor = builders.token_ref("tok-1", 3)
    assert isinstance(anchor.tokenRef, TokenRef)
    assert anchor.tokenRef.tokenIndex == 3
    assert anchor.tokenRef.tokenizationId.value == "tok-1"


def test_token_ref_rejects_empty_tokenization_id() -> None:
    with pytest.raises(builders.BuildError):
        builders.token_ref("", 0)


def test_token_ref_rejects_negative_index() -> None:
    with pytest.raises(builders.BuildError):
        builders.token_ref("tok-1", -1)


def test_temporal_sets_temporal_span() -> None:
    anchor = builders.temporal(100, 900)
    assert isinstance(anchor.temporalSpan, TemporalSpan)
    assert anchor.temporalSpan.start == 100
    assert anchor.temporalSpan.ending == 900


def test_temporal_rejects_inverted_span() -> None:
    with pytest.raises(builders.BuildError):
        builders.temporal(900, 100)


def test_bbox_builds_bounding_box() -> None:
    box = builders.bbox(1, 2, 10, 20)
    assert isinstance(box, BoundingBox)
    assert (box.x, box.y, box.width, box.height) == (1, 2, 10, 20)


def test_bbox_rejects_zero_dimension() -> None:
    with pytest.raises(builders.BuildError):
        builders.bbox(0, 0, 0, 10)
    with pytest.raises(builders.BuildError):
        builders.bbox(0, 0, 10, 0)


def test_keyframe_carries_box_and_time() -> None:
    box = builders.bbox(0, 0, 4, 4)
    frame = builders.keyframe(500, box)
    assert isinstance(frame, Keyframe)
    assert frame.timeMs == 500
    # didactic re-validates embedded models, so compare by value, not identity.
    assert frame.bbox.model_dump() == box.model_dump()


def test_keyframe_rejects_negative_time() -> None:
    with pytest.raises(builders.BuildError):
        builders.keyframe(-1, builders.bbox(0, 0, 4, 4))


def test_spatio_temporal_wraps_keyframes() -> None:
    box = builders.bbox(0, 0, 4, 4)
    frames = [builders.keyframe(0, box), builders.keyframe(100, box)]
    anchor = builders.spatio_temporal(
        TemporalSpan(start=0, ending=100),
        frames,
        "linear",
    )
    value = anchor.spatioTemporalAnchor
    assert isinstance(value, SpatioTemporalAnchor)
    assert value.interpolation == "linear"
    assert value.keyframes is not None
    assert len(value.keyframes) == 2


def test_spatio_temporal_accepts_community_interpolation() -> None:
    # the interpolation vocabulary is open; an unknown non-empty value passes.
    box = builders.bbox(0, 0, 4, 4)
    anchor = builders.spatio_temporal(
        TemporalSpan(start=0, ending=10),
        [builders.keyframe(0, box)],
        "bezier",
    )
    assert anchor.spatioTemporalAnchor is not None
    assert anchor.spatioTemporalAnchor.interpolation == "bezier"


def test_spatio_temporal_requires_keyframes() -> None:
    with pytest.raises(builders.BuildError):
        builders.spatio_temporal(TemporalSpan(start=0, ending=10), [])


# cross-reference helpers --------------------------------------------------


def test_new_uuid_is_unique() -> None:
    first = builders.new_uuid()
    second = builders.new_uuid()
    assert first.value != second.value


def test_reference_passes_through_at_uri() -> None:
    uri = "at://did:plc:abc/pub.layers.expression.expression/e1"
    assert builders.reference(uri) == uri


def test_reference_passes_through_pending_id() -> None:
    pending = builders.PendingId("expr-local-1")
    assert builders.reference(pending) == "expr-local-1"
    assert isinstance(pending, str)


def test_reference_reads_uri_field_from_model() -> None:
    class _Published:
        uri = "at://did:plc:abc/pub.layers.media.media/m1"

    assert (
        builders.reference(_Published())  # ty: ignore[invalid-argument-type]
        == "at://did:plc:abc/pub.layers.media.media/m1"
    )


def test_reference_passes_through_empty_string() -> None:
    # an explicit AT-URI string passes through unchecked, including the empty
    # string: reference does not validate AT-URI shape, only model resolution.
    assert builders.reference("") == ""


def test_reference_rejects_unpublished_model() -> None:
    expr = Expression(
        id="doc-1",
        kind="sentence",
        createdAt=datetime.now(UTC),
        text="hello",
    )
    with pytest.raises(builders.BuildError):
        builders.reference(expr)


# layer builder ------------------------------------------------------------


def _builder() -> builders.LayerBuilder:
    return builders.LayerBuilder(
        "at://did:plc:abc/pub.layers.expression.expression/e1",
        "token-tag",
        datetime.now(UTC),
        subkind="pos",
        tokenization_id="tok-1",
    )


def test_layer_builder_mints_uuids_per_annotation() -> None:
    builder = _builder()
    builder.add(anchor=builders.token_ref("tok-1", 0), label="NOUN", token_index=0)
    builder.add(anchor=builders.token_ref("tok-1", 1), label="VERB", token_index=1)
    layer = builder.build()
    assert len(layer.annotations) == 2
    uuids = {annotation.uuid.value for annotation in layer.annotations}
    assert len(uuids) == 2
    assert all(value for value in uuids)


def test_layer_builder_carries_layer_facets() -> None:
    builder = _builder()
    builder.add(label="NOUN", token_index=0)
    layer = builder.build()
    assert layer.kind == "token-tag"
    assert layer.subkind == "pos"
    assert layer.tokenizationId is not None
    assert layer.tokenizationId.value == "tok-1"
    assert layer.expression.endswith("/e1")


def test_layer_builder_validates_confidence_range() -> None:
    builder = _builder()
    with pytest.raises(builders.BuildError):
        builder.add(label="NOUN", confidence=2000)


def test_layer_builder_accepts_in_range_confidence() -> None:
    builder = _builder()
    annotation = builder.add(label="NOUN", confidence=750)
    assert annotation.confidence == 750


def test_layer_builder_rejects_negative_token_index() -> None:
    builder = _builder()
    with pytest.raises(builders.BuildError):
        builder.add(label="NOUN", token_index=-1)


def test_layer_builder_requires_an_annotation() -> None:
    builder = _builder()
    with pytest.raises(builders.BuildError):
        builder.build()


def test_layer_builder_rejects_empty_kind() -> None:
    with pytest.raises(builders.BuildError):
        builders.LayerBuilder(
            "at://did:plc:abc/pub.layers.expression.expression/e1",
            "",
            datetime.now(UTC),
        )


def test_layer_builder_rejects_empty_formalism() -> None:
    # formalism is an open vocabulary, so an empty string is the only rejection.
    with pytest.raises(builders.BuildError):
        builders.LayerBuilder(
            "at://did:plc:abc/pub.layers.expression.expression/e1",
            "tree",
            datetime.now(UTC),
            formalism="",
        )


def test_layer_builder_accepts_community_formalism() -> None:
    builder = builders.LayerBuilder(
        "at://did:plc:abc/pub.layers.expression.expression/e1",
        "tree",
        datetime.now(UTC),
        formalism="universal-dependencies",
    )
    builder.add(label="root", token_index=0)
    layer = builder.build()
    assert layer.formalism == "universal-dependencies"


def test_layer_builder_accepts_pending_expression_id() -> None:
    pending = builders.PendingId("expr-local-1")
    builder = builders.LayerBuilder(pending, "span", datetime.now(UTC))
    builder.add(anchor=builders.span(0, 4), label="PER")
    layer = builder.build()
    assert layer.expression == "expr-local-1"
