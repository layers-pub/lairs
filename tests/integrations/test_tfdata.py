"""Unit and integration tests for lairs.integrations.tfdata.

The Arrow-schema to feature-spec derivation is exercised without tensorflow; the
tests that build a real ``tf.data.Dataset`` skip cleanly when the optional
``lairs[tf]`` extra is absent.
"""

from __future__ import annotations

import sys

import pyarrow as pa
import pytest

from lairs.integrations.ports import Exporter
from lairs.integrations.tfdata import (
    TfDataExporter,
    TfDataSpec,
    TfFeatureSpec,
    feature_specs_of,
    token_of,
)


def test_name() -> None:
    """The exporter advertises the ``tfdata`` registry name."""
    assert TfDataExporter.name == "tfdata"


def test_binds_to_exporter_port() -> None:
    """An instance satisfies the runtime-checkable Exporter protocol."""
    assert isinstance(TfDataExporter(), Exporter)


def test_import_does_not_pull_in_tensorflow() -> None:
    """Importing the module must not import tensorflow eagerly."""
    assert "tensorflow" not in sys.modules


def test_token_of_scalars() -> None:
    """Scalar Arrow types map to the expected tensorflow dtype tokens."""
    assert token_of(pa.int64()) == ("int64", False)
    assert token_of(pa.int32()) == ("int64", False)
    assert token_of(pa.bool_()) == ("bool", False)
    assert token_of(pa.float64()) == ("float64", False)
    assert token_of(pa.float32()) == ("float32", False)
    assert token_of(pa.string()) == ("string", False)
    assert token_of(pa.large_string()) == ("string", False)
    assert token_of(pa.binary()) == ("string", False)


def test_token_of_lists_are_sequences() -> None:
    """List and large-list types become sequences over their element token."""
    assert token_of(pa.list_(pa.int64())) == ("int64", True)
    assert token_of(pa.large_list(pa.string())) == ("string", True)


def test_token_of_unknown_falls_back_to_string() -> None:
    """An unrecognised Arrow type collapses to the string token."""
    assert token_of(pa.date32()) == ("string", False)


def test_feature_specs_of_full_schema() -> None:
    """Every column becomes a feature spec in schema order by default."""
    table = pa.table(
        {
            "tokens": [["a", "b"], ["c"]],
            "label": [1, 0],
            "score": [0.5, 0.25],
        },
    )
    specs = feature_specs_of(table.schema)
    assert specs == (
        TfFeatureSpec(name="tokens", dtype="string", is_sequence=True),
        TfFeatureSpec(name="label", dtype="int64", is_sequence=False),
        TfFeatureSpec(name="score", dtype="float64", is_sequence=False),
    )


def test_feature_specs_of_selects_and_orders_columns() -> None:
    """The columns argument selects and reorders, skipping absent names."""
    table = pa.table({"a": [1], "b": ["x"], "c": [1.0]})
    specs = feature_specs_of(table.schema, columns=("c", "a", "missing"))
    assert tuple(spec.name for spec in specs) == ("c", "a")


def test_feature_specs_of_empty_schema() -> None:
    """An empty schema yields no feature specs."""
    assert feature_specs_of(pa.schema([])) == ()


def test_spec_defaults() -> None:
    """The default spec keeps all columns and neither shuffles nor batches."""
    spec = TfDataSpec()
    assert spec.columns == ()
    assert spec.batch_size is None
    assert spec.shuffle_buffer is None
    assert spec.drop_remainder is False


def test_export_without_tensorflow_raises_clear_error() -> None:
    """Without tensorflow, export raises an ImportError naming the extra."""
    if "tensorflow" in sys.modules:
        pytest.skip("tensorflow is installed; the lazy-import error cannot fire")
    table = pa.table({"a": [1, 2]})
    with pytest.raises(ImportError, match=r"lairs\[tf\]"):
        TfDataExporter().export(table)


@pytest.mark.integration
def test_export_builds_dataset() -> None:
    """With tensorflow present, export builds a column-keyed dataset."""
    tf = pytest.importorskip("tensorflow")
    table = pa.table({"label": [1, 0, 1], "text": ["a", "b", "c"]})
    dataset = TfDataExporter().export(table)
    assert isinstance(dataset, tf.data.Dataset)
    rows = list(dataset.as_numpy_iterator())
    assert len(rows) == 3
    assert rows[0]["label"] == 1
    assert rows[0]["text"] == b"a"


@pytest.mark.integration
def test_export_batches_and_selects_columns() -> None:
    """The spec selects columns and batches the emitted dataset."""
    tf = pytest.importorskip("tensorflow")
    table = pa.table({"a": [1, 2, 3, 4], "b": [10, 20, 30, 40]})
    spec = TfDataSpec(columns=("b",), batch_size=2, drop_remainder=True)
    dataset = TfDataExporter().export(table, spec=spec)
    assert isinstance(dataset, tf.data.Dataset)
    batches = list(dataset.as_numpy_iterator())
    assert len(batches) == 2
    assert set(batches[0]) == {"b"}
    assert list(batches[0]["b"]) == [10, 20]


@pytest.mark.integration
def test_export_handles_sequence_columns() -> None:
    """List-valued columns export as ragged tensors."""
    tf = pytest.importorskip("tensorflow")
    table = pa.table({"tokens": [["a", "b"], ["c"]]})
    dataset = TfDataExporter().export(table)
    assert isinstance(dataset, tf.data.Dataset)
    rows = list(dataset.as_numpy_iterator())
    assert list(rows[0]["tokens"]) == [b"a", b"b"]
    assert list(rows[1]["tokens"]) == [b"c"]
