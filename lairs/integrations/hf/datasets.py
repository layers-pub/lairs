"""HuggingFace ``datasets`` exporter.

Builds a ``datasets.Dataset`` straight from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. Because the Arrow flattening
done by :mod:`lairs.store.arrow` already resolves the polymorphic Layers anchors
into typed columns, the schema logic here stays thin: the exporter wraps the
Arrow table (near zero-copy), optionally selects columns for a task template, and
derives a HuggingFace ``Features`` mapping from the generated model field specs
through :mod:`lairs.data.features`.

``datasets`` is an optional dependency provided by the ``lairs[hf]`` extra. It is
imported lazily inside the methods that need it, so importing this module never
pulls ``datasets`` in; the concrete return types are bound only under
``TYPE_CHECKING``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pyarrow as pa
    from datasets import (  # ty: ignore[unresolved-import]
        Dataset,
        IterableDataset,
        Value,
    )
    from datasets import Features as HfFeatures  # ty: ignore[unresolved-import]
    from datasets import Sequence as HfSequence  # ty: ignore[unresolved-import]

    from lairs._types import JsonValue
    from lairs.data.features import Features

__all__ = [
    "TASK_TEMPLATES",
    "ExportSpec",
    "HuggingFaceExporter",
    "TaskTemplate",
    "hf_features_from",
    "task_template_for",
]

type Shape = Literal["nested", "exploded"]
"""The tabular shape an Arrow view is exported in.

``nested`` keeps one row per expression with annotations as sequence-valued
columns; ``exploded`` keeps one row per annotation. The Arrow builders in
:mod:`lairs.store.arrow` already produce one shape or the other, so the shape is
descriptive metadata the exporter records rather than a re-shaping step.
"""


class _DatasetsModule(Protocol):
    """The slice of the ``datasets`` module surface this exporter uses.

    Typing the lazily-imported module against a protocol keeps the optional
    dependency off the import path while still avoiding ``Any``: the exporter
    only touches the ``Dataset``, ``IterableDataset``, ``Features``, and
    ``Value`` constructors.
    """

    Dataset: type[Dataset]
    IterableDataset: type[IterableDataset]
    Features: type[HfFeatures]
    Sequence: type[HfSequence]
    Value: type[Value]


class TaskTemplate(dx.Model):
    """A canonical HuggingFace task shape for a Layers annotation layer.

    A template maps a Layers ``(kind, subkind, formalism)`` triple to a named
    HuggingFace task and the columns that task expects, so a token-classification
    or span layer exports under the conventional column names HuggingFace tooling
    recognises.

    Parameters
    ----------
    task : str
        The canonical HuggingFace task name (for example
        ``"token-classification"``).
    kind : str
        The Layers annotation kind this template applies to.
    subkind : str or None, optional
        The Layers annotation subkind, when the template is subkind-specific.
    formalism : str or None, optional
        The Layers formalism, when the template is formalism-specific.
    columns : tuple of str, optional
        The columns the task shape expects, in order.
    """

    task: str = dx.field(description="canonical huggingface task name")
    kind: str = dx.field(description="layers annotation kind the template matches")
    subkind: str | None = dx.field(
        default=None,
        description="layers annotation subkind the template matches",
    )
    formalism: str | None = dx.field(
        default=None,
        description="layers formalism the template matches",
    )
    columns: tuple[str, ...] = dx.field(
        default=(),
        description="columns the task shape expects, in order",
    )


# the catalogue of task templates mapping layers (kind, subkind, formalism) to
# canonical huggingface dataset shapes. matching is most-specific-first: a
# template constraining a subkind or formalism wins over a kind-only template.
TASK_TEMPLATES: tuple[TaskTemplate, ...] = (
    TaskTemplate(
        task="token-classification",
        kind="token-tag",
        subkind="pos",
        columns=("tokens", "labels", "token_index"),
    ),
    TaskTemplate(
        task="token-classification",
        kind="token-tag",
        subkind="ner",
        columns=("tokens", "labels", "token_index"),
    ),
    TaskTemplate(
        task="token-classification",
        kind="token-tag",
        columns=("tokens", "labels", "token_index"),
    ),
    TaskTemplate(
        task="extractive-question-answering",
        kind="span",
        columns=("label", "byte_start", "byte_end"),
    ),
    TaskTemplate(
        task="dependency-parsing",
        kind="tree",
        formalism="universal-dependencies",
        columns=("token_index", "label", "byte_start", "byte_end"),
    ),
    TaskTemplate(
        task="dependency-parsing",
        kind="tree",
        columns=("token_index", "label", "byte_start", "byte_end"),
    ),
    TaskTemplate(
        task="text-classification",
        kind="document-tag",
        columns=("label",),
    ),
    TaskTemplate(
        task="automatic-speech-recognition",
        kind="tier",
        subkind="forced-alignment",
        columns=("label", "t_start_ms", "t_end_ms"),
    ),
    TaskTemplate(
        task="object-detection",
        kind="span",
        subkind="bounding-box",
        columns=("label", "bbox_x", "bbox_y", "bbox_w", "bbox_h"),
    ),
    TaskTemplate(
        task="object-tracking",
        kind="span",
        subkind="spatio-temporal",
        columns=("label", "t_start_ms", "t_end_ms", "bbox_x", "bbox_y"),
    ),
)


def task_template_for(
    kind: str,
    *,
    subkind: str | None = None,
    formalism: str | None = None,
) -> TaskTemplate | None:
    """Return the most specific task template matching a Layers triple.

    A template matches when its ``kind`` equals ``kind`` and each of its set
    ``subkind`` and ``formalism`` fields equals the corresponding argument.
    Templates are ranked by specificity, so a template constraining a subkind or
    formalism is preferred over a kind-only template for the same kind.

    Parameters
    ----------
    kind : str
        The Layers annotation kind to match.
    subkind : str or None, optional
        The Layers annotation subkind, when known.
    formalism : str or None, optional
        The Layers formalism, when known.

    Returns
    -------
    TaskTemplate or None
        The best-matching template, or ``None`` when no template applies.
    """
    best: TaskTemplate | None = None
    best_score = -1
    for template in TASK_TEMPLATES:
        if template.kind != kind:
            continue
        if template.subkind is not None and template.subkind != subkind:
            continue
        if template.formalism is not None and template.formalism != formalism:
            continue
        score = int(template.subkind is not None) + int(template.formalism is not None)
        if score > best_score:
            best = template
            best_score = score
    return best


class ExportSpec(dx.Model):
    """An export specification controlling the HuggingFace dataset shape.

    The Arrow flattening has already done the heavy lifting, so the spec only
    records the tabular shape, an optional column projection, and an optional
    canonical task name. It is a plain didactic model so it is serialisable and
    carries cleanly into a dataset card's provenance.

    Parameters
    ----------
    shape : {"nested", "exploded"}, optional
        The tabular shape of the Arrow view being exported.
    columns : tuple of str or None, optional
        An optional projection: when set, only these columns are kept, in this
        order. Columns absent from the view are skipped.
    task : str or None, optional
        An optional canonical HuggingFace task name, recorded for downstream
        tooling and dataset-card provenance.
    """

    shape: Shape = dx.field(
        default="nested",
        description="tabular shape of the exported view",
    )
    columns: tuple[str, ...] | None = dx.field(
        default=None,
        description="optional ordered column projection",
    )
    task: str | None = dx.field(
        default=None,
        description="canonical huggingface task name, when a template applies",
    )

    @classmethod
    def for_template(
        cls,
        template: TaskTemplate,
        *,
        shape: Shape = "exploded",
    ) -> ExportSpec:
        """Build a spec that selects a task template's columns.

        Parameters
        ----------
        template : TaskTemplate
            The task template whose columns to project and whose task to record.
        shape : {"nested", "exploded"}, optional
            The tabular shape of the view being exported.

        Returns
        -------
        ExportSpec
            A spec projecting the template's columns and recording its task.
        """
        return cls(shape=shape, columns=template.columns, task=template.task)


# the lairs dtype tokens (from lairs.data.features) mapped to huggingface
# ``datasets`` ``Value`` dtype strings. sequence tokens are handled separately by
# ``hf_features_from``; struct tokens degrade to a json string column.
_VALUE_DTYPES: dict[str, str] = {
    "string": "string",
    "bool": "bool",
    "int64": "int64",
    "float64": "float64",
    "binary": "binary",
    "timestamp": "timestamp[ms]",
    "struct": "string",
}


def _hf_dtype_token(token: str) -> str:
    """Return the HuggingFace ``Value`` dtype for a lairs feature token.

    Sequence tokens (``sequence<inner>``) are reduced to their inner token's
    dtype; the caller wraps that in a ``datasets.Sequence`` when building the
    feature. Unknown tokens degrade to ``"string"`` so the mapping is total.

    Parameters
    ----------
    token : str
        A lairs feature dtype token from :func:`lairs.data.features.dtype_of`.

    Returns
    -------
    str
        The corresponding HuggingFace ``Value`` dtype string.
    """
    if token.startswith("sequence<") and token.endswith(">"):
        return _hf_dtype_token(token[len("sequence<") : -1])
    return _VALUE_DTYPES.get(token, "string")


def _is_sequence_token(token: str) -> bool:
    """Return whether a lairs feature token denotes a sequence."""
    return token.startswith("sequence<") and token.endswith(">")


def hf_features_from(features: Features) -> HfFeatures:
    """Derive a HuggingFace ``Features`` mapping from a lairs feature schema.

    Each lairs :class:`~lairs.data.features.FeatureSpec` becomes a HuggingFace
    ``Value`` (or a ``Sequence`` of a ``Value`` for sequence tokens). Because the
    lairs features are read off the generated model field specs, the resulting
    HuggingFace schema always matches the lexicons.

    Parameters
    ----------
    features : lairs.data.features.Features
        The lairs feature schema, typically from
        :func:`lairs.data.features.features_of`.

    Returns
    -------
    datasets.Features
        The HuggingFace feature mapping.

    Raises
    ------
    ImportError
        When the optional ``datasets`` dependency is not installed.
    """
    datasets = _import_datasets()
    mapping: dict[str, Value | HfSequence] = {}
    for spec in features.specs:
        value = datasets.Value(_hf_dtype_token(spec.dtype))
        mapping[spec.name] = (
            datasets.Sequence(value) if _is_sequence_token(spec.dtype) else value
        )
    return datasets.Features(mapping)


class HuggingFaceExporter:
    """An exporter that emits a ``datasets.Dataset`` from an Arrow view.

    The exporter binds to the :class:`~lairs.integrations.ports.Exporter` port
    with the Arrow table as the view, :class:`ExportSpec` as the spec, and a
    ``datasets.Dataset`` as the produced object. Because the Arrow view already
    carries typed anchor columns, the exporter only applies the spec's column
    projection and hands the table to ``datasets`` near zero-copy.
    """

    name = "hf"

    def export(self, view: pa.Table, *, spec: ExportSpec | None = None) -> Dataset:
        """Export an Arrow view to a HuggingFace dataset.

        The export wraps the Arrow table directly: ``datasets`` builds an
        Arrow-backed dataset with no row-wise copy. When the spec carries a
        column projection, the table is narrowed to those columns first.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : ExportSpec or None, optional
            An optional export specification (shape, column projection, task).

        Returns
        -------
        datasets.Dataset
            The exported, Arrow-backed dataset.

        Raises
        ------
        ImportError
            When the optional ``datasets`` dependency is not installed.
        """
        datasets = _import_datasets()
        projected = _project(view, spec.columns if spec is not None else None)
        return datasets.Dataset(projected)

    def to_hf_iterable(
        self,
        source: Callable[[], Iterator[pa.RecordBatch]],
        *,
        spec: ExportSpec | None = None,
    ) -> IterableDataset:
        """Build a streaming ``datasets.IterableDataset`` from a batch source.

        The source is a zero-argument factory returning a fresh iterator of Arrow
        record batches, for example one driven by a PDS cursor or a Repository
        scan, so a large corpus trains without a full download. Each batch is
        narrowed by the spec's column projection before its rows are yielded.

        Parameters
        ----------
        source : collections.abc.Callable
            A zero-argument factory returning a fresh iterator of Arrow record
            batches.
        spec : ExportSpec or None, optional
            An optional export specification (column projection).

        Returns
        -------
        datasets.IterableDataset
            A streaming dataset over the batch source.

        Raises
        ------
        ImportError
            When the optional ``datasets`` dependency is not installed.
        """
        datasets = _import_datasets()
        columns = spec.columns if spec is not None else None

        def generator() -> Iterator[dict[str, JsonValue]]:
            for batch in source():
                table = _project_batch(batch, columns)
                yield from table.to_pylist()

        return datasets.IterableDataset.from_generator(generator)


def _import_datasets() -> _DatasetsModule:
    """Import the optional ``datasets`` module, with a clear error when absent.

    Returns
    -------
    _DatasetsModule
        The imported ``datasets`` module, narrowed to the surface this exporter
        uses.

    Raises
    ------
    ImportError
        When the ``datasets`` package is not installed.
    """
    try:
        import datasets  # noqa: PLC0415  # ty: ignore[unresolved-import]
    except ImportError as exc:
        msg = (
            "the HuggingFace exporter requires the optional 'lairs[hf]' extra "
            "(datasets)"
        )
        raise ImportError(msg) from exc
    return datasets


def _project(view: pa.Table, columns: tuple[str, ...] | None) -> pa.Table:
    """Return the view narrowed to ``columns`` (in order), skipping absent ones.

    Parameters
    ----------
    view : pyarrow.Table
        The table to project.
    columns : tuple of str or None
        The ordered columns to keep, or ``None`` to keep every column.

    Returns
    -------
    pyarrow.Table
        The projected table; the original table when ``columns`` is ``None``.
    """
    if columns is None:
        return view
    present = [name for name in columns if name in view.column_names]
    return view.select(present)


def _project_batch(
    batch: pa.RecordBatch,
    columns: tuple[str, ...] | None,
) -> pa.Table:
    """Return a record batch as a table narrowed to ``columns`` (in order).

    Parameters
    ----------
    batch : pyarrow.RecordBatch
        The record batch to project.
    columns : tuple of str or None
        The ordered columns to keep, or ``None`` to keep every column.

    Returns
    -------
    pyarrow.Table
        The projected single-batch table.
    """
    import pyarrow as pa  # noqa: PLC0415 - lazy: keep pyarrow imports local to the data path

    table = pa.Table.from_batches([batch])
    return _project(table, columns)
