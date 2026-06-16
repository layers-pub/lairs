"""Unit tests for lairs.data.features."""

from __future__ import annotations

from datetime import datetime

import didactic.api as dx

from lairs.data import features
from lairs.data.features import Features, FeatureSpec, dtype_of, features_of
from lairs.records._generated.expression import Expression


class _Inner(dx.Model):
    """A throwaway nested model used as an embed target."""

    value: str = dx.field(default="")


class _Sample(dx.Model):
    """A throwaway model exercising every dtype-mapping branch."""

    name: str
    count: int
    score: float = dx.field(default=0.0)
    flag: bool = dx.field(default=False)
    when: datetime = dx.field(extras={"format": "datetime"})
    note: str | None = dx.field(default=None)
    tags: tuple[str, ...] = dx.field(default_factory=tuple)
    sizes: tuple[int, ...] | None = dx.field(default_factory=tuple)
    inner: dx.Embed[_Inner] | None = dx.field(default=None)
    inners: tuple[dx.Embed[_Inner], ...] = dx.field(default_factory=tuple)


class _Opaque(dx.Model):
    """A throwaway model carrying an opaque payload field."""

    label: str = dx.field(default="")
    payload: bytes = dx.field(default=b"", opaque=True)


def test_exports() -> None:
    assert set(features.__all__) == {
        "FeatureSpec",
        "Features",
        "dtype_of",
        "features_of",
    }


def test_feature_spec_construction() -> None:
    spec = FeatureSpec(name="text", dtype="string")
    assert spec.name == "text"
    assert spec.dtype == "string"
    assert spec.nullable is True


def test_features_default_is_empty() -> None:
    assert Features().specs == ()


def test_features_roundtrip() -> None:
    feats = Features(specs=(FeatureSpec(name="text", dtype="string"),))
    back = Features.model_validate_json(feats.model_dump_json())
    assert back == feats


def test_features_names_and_get() -> None:
    feats = Features(
        specs=(
            FeatureSpec(name="a", dtype="string"),
            FeatureSpec(name="b", dtype="int64"),
        ),
    )
    assert feats.names() == ("a", "b")
    got = feats.get("b")
    assert got is not None
    assert got.dtype == "int64"
    assert feats.get("missing") is None


def test_dtype_of_scalars() -> None:
    assert dtype_of(str) == "string"
    assert dtype_of(int) == "int64"
    assert dtype_of(float) == "float64"
    assert dtype_of(bool) == "bool"
    assert dtype_of(datetime) == "timestamp"


def test_dtype_of_optional_unwraps() -> None:
    assert dtype_of(str | None) == "string"
    assert dtype_of(int | None) == "int64"


def test_dtype_of_sequences() -> None:
    assert dtype_of(tuple[str, ...]) == "sequence<string>"
    assert dtype_of(tuple[int, ...] | None) == "sequence<int64>"


def test_dtype_of_embed_is_struct() -> None:
    assert dtype_of(dx.Embed[_Inner]) == "struct"
    assert dtype_of(dx.Embed[_Inner] | None) == "struct"
    assert dtype_of(tuple[dx.Embed[_Inner], ...]) == "sequence<struct>"


def test_features_of_matches_field_specs() -> None:
    feats = features_of(_Sample)
    assert feats.names() == tuple(_Sample.__field_specs__)


def test_features_of_dtypes_and_nullability() -> None:
    feats = features_of(_Sample)
    by_name = {spec.name: spec for spec in feats.specs}
    assert by_name["name"].dtype == "string"
    assert by_name["name"].nullable is False
    assert by_name["count"].dtype == "int64"
    assert by_name["score"].dtype == "float64"
    assert by_name["flag"].dtype == "bool"
    assert by_name["when"].dtype == "timestamp"
    assert by_name["note"].dtype == "string"
    assert by_name["note"].nullable is True
    assert by_name["tags"].dtype == "sequence<string>"
    assert by_name["sizes"].dtype == "sequence<int64>"
    assert by_name["inner"].dtype == "struct"
    assert by_name["inners"].dtype == "sequence<struct>"


def test_features_of_opaque_is_binary() -> None:
    feats = features_of(_Opaque)
    by_name = {spec.name: spec for spec in feats.specs}
    assert by_name["payload"].dtype == "binary"


def test_features_of_generated_expression() -> None:
    feats = features_of(Expression)
    # the derived order and names must mirror the generated field specs exactly.
    assert feats.names() == tuple(Expression.__field_specs__)
    by_name = {spec.name: spec for spec in feats.specs}
    assert by_name["id"].dtype == "string"
    assert by_name["id"].nullable is False
    assert by_name["createdAt"].dtype == "timestamp"
    assert by_name["anchor"].dtype == "struct"
    assert by_name["languages"].dtype == "sequence<string>"
    assert by_name["text"].nullable is True
