"""Unit and integration tests for lairs.integrations.hf.datasets."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import didactic.api as dx
import pytest

from lairs.data.features import Features, FeatureSpec
from lairs.integrations.hf import datasets as ds
from lairs.integrations.hf.datasets import (
    TASK_TEMPLATES,
    ExportSpec,
    HuggingFaceExporter,
    TaskTemplate,
    hf_features_from,
    task_template_for,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pyarrow as pa


def test_name() -> None:
    assert HuggingFaceExporter.name == "hf"


def test_binds_to_exporter_port() -> None:
    # the exporter exposes the port's name attribute and export method.
    exporter = HuggingFaceExporter()
    assert exporter.name == "hf"
    assert callable(exporter.export)
    assert callable(exporter.to_hf_iterable)


def test_task_template_is_a_model() -> None:
    template = TaskTemplate(task="t", kind="span")
    assert isinstance(template, dx.Model)
    assert template.subkind is None
    assert template.columns == ()


def test_export_spec_is_a_model() -> None:
    spec = ExportSpec()
    assert isinstance(spec, dx.Model)
    assert spec.shape == "nested"
    assert spec.columns is None


def test_export_spec_for_template_projects_columns() -> None:
    template = TaskTemplate(
        task="token-classification",
        kind="token-tag",
        columns=("a", "b"),
    )
    spec = ExportSpec.for_template(template)
    assert spec.columns == ("a", "b")
    assert spec.task == "token-classification"
    assert spec.shape == "exploded"


@pytest.mark.parametrize(
    ("kind", "subkind", "formalism", "expected_task"),
    [
        ("token-tag", "pos", None, "token-classification"),
        ("token-tag", "ner", None, "token-classification"),
        ("token-tag", None, None, "token-classification"),
        ("span", None, None, "extractive-question-answering"),
        ("tree", None, "universal-dependencies", "dependency-parsing"),
        ("tree", None, None, "dependency-parsing"),
        ("document-tag", None, None, "text-classification"),
        ("tier", "forced-alignment", None, "automatic-speech-recognition"),
        ("span", "bounding-box", None, "object-detection"),
        ("span", "spatio-temporal", None, "object-tracking"),
    ],
)
def test_task_template_for_matches(
    kind: str,
    subkind: str | None,
    formalism: str | None,
    expected_task: str,
) -> None:
    template = task_template_for(kind, subkind=subkind, formalism=formalism)
    assert template is not None
    assert template.task == expected_task


def test_task_template_for_unknown_kind_returns_none() -> None:
    assert task_template_for("nonexistent-kind") is None


def test_task_template_for_prefers_specific_match() -> None:
    # a subkind-specific template wins over the kind-only fallback.
    template = task_template_for("span", subkind="bounding-box")
    assert template is not None
    assert template.task == "object-detection"


def test_task_template_catalogue_is_nonempty() -> None:
    assert len(TASK_TEMPLATES) > 0
    assert all(isinstance(t, TaskTemplate) for t in TASK_TEMPLATES)


def test_project_keeps_present_columns_in_order() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1], "b": [2], "c": [3]})
    projected = ds._project(table, ("c", "a", "missing"))
    assert projected.column_names == ["c", "a"]


def test_project_none_returns_table_unchanged() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1]})
    assert ds._project(table, None) is table


def test_hf_dtype_token_mapping() -> None:
    assert ds._hf_dtype_token("string") == "string"
    assert ds._hf_dtype_token("int64") == "int64"
    assert ds._hf_dtype_token("timestamp") == "timestamp[ms]"
    assert ds._hf_dtype_token("struct") == "string"
    # sequence tokens reduce to their inner dtype.
    assert ds._hf_dtype_token("sequence<int64>") == "int64"
    # unknown tokens degrade to string.
    assert ds._hf_dtype_token("mystery") == "string"


def test_is_sequence_token() -> None:
    assert ds._is_sequence_token("sequence<string>")
    assert not ds._is_sequence_token("string")


def test_export_without_datasets_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # simulate the optional 'datasets' library being absent so the clear error
    # path runs even though the dev environment installs lairs[hf].
    monkeypatch.setitem(sys.modules, "datasets", None)
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1, 2]})
    with pytest.raises(ImportError, match="lairs\\[hf\\]"):
        HuggingFaceExporter().export(table)


def test_hf_features_from_without_datasets_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "datasets", None)
    features = Features(specs=(FeatureSpec(name="a", dtype="string"),))
    with pytest.raises(ImportError, match="lairs\\[hf\\]"):
        hf_features_from(features)


@pytest.mark.integration
def test_export_live() -> None:
    pa = pytest.importorskip("pyarrow")
    pytest.importorskip("datasets")
    table = pa.table({"label": ["a", "b"], "byte_start": [0, 3], "byte_end": [2, 5]})
    dataset = HuggingFaceExporter().export(table)
    assert len(dataset) == 2
    assert dataset.column_names == ["label", "byte_start", "byte_end"]


@pytest.mark.integration
def test_export_with_projection_live() -> None:
    pa = pytest.importorskip("pyarrow")
    pytest.importorskip("datasets")
    table = pa.table({"label": ["a"], "byte_start": [0], "extra": [9]})
    spec = ExportSpec(columns=("label", "byte_start"))
    dataset = HuggingFaceExporter().export(table, spec=spec)
    assert dataset.column_names == ["label", "byte_start"]


@pytest.mark.integration
def test_hf_features_from_live() -> None:
    pytest.importorskip("datasets")
    features = Features(
        specs=(
            FeatureSpec(name="text", dtype="string"),
            FeatureSpec(name="tokens", dtype="sequence<string>"),
        ),
    )
    hf = hf_features_from(features)
    assert set(hf) == {"text", "tokens"}


@pytest.mark.integration
def test_to_hf_iterable_live() -> None:
    pa = pytest.importorskip("pyarrow")
    pytest.importorskip("datasets")

    def source() -> Iterator[pa.RecordBatch]:
        yield pa.record_batch({"label": ["a", "b"]})

    iterable = HuggingFaceExporter().to_hf_iterable(source)
    rows = list(iterable)
    assert [row["label"] for row in rows] == ["a", "b"]
