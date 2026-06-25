"""PyTorch data-plane exporter.

Emits PyTorch datasets from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. The exporter produces a
map-style :class:`torch.utils.data.Dataset`, an
:class:`torch.utils.data.IterableDataset` variant, and a ``collate`` helper,
bundled in a :class:`TorchExportResult`.

PyTorch is an optional dependency (the ``lairs[torch]`` extra). It is imported
lazily inside the methods that need it, with a clear error when it is missing,
so importing this module never pulls ``torch`` in. The column-selection and
batching logic is pure Python over the Arrow table, so it is exercisable without
``torch`` installed.

The Arrow view already carries typed anchor columns, so per-row union dispatch
is unnecessary: numeric and anchor columns become tensors directly, and the
remaining columns are passed through as Python values. The flat view carries no
blob payloads, so media bytes are not materialised here; the exporter records
the requested media-resolution intent on its result for a downstream loader
transform (which owns the :mod:`lairs.media` anchor-aware resolver and the blob
transport) to act on.
"""

from __future__ import annotations

from types import ModuleType  # noqa: TC003  (runtime: return annotation)
from typing import TYPE_CHECKING

import didactic.api as dx
import pyarrow as pa

from lairs._types import JsonValue  # noqa: TC001  (runtime: model construction)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from torch import Tensor
    from torch.utils.data import (
        Dataset,
        IterableDataset,
    )

__all__ = [
    "TorchExportResult",
    "TorchExportSpec",
    "TorchExporter",
]

# the dtype tokens, as produced by lairs.data.features, that map to a tensor.
_TENSOR_DTYPE_TOKENS: frozenset[str] = frozenset(
    {"bool", "int64", "float64", "timestamp"},
)


class TorchExportSpec(dx.Model):
    """The export specification for the PyTorch exporter.

    Selects which Arrow columns become tensor features, which are passed through
    as plain Python values, and whether media references are resolved as records
    flow. When ``columns`` is unset every column is kept; when ``tensor_columns``
    is unset the numeric (and anchor) columns are inferred from the Arrow schema.

    Attributes
    ----------
    columns : tuple of str or None, optional
        The ordered subset of Arrow columns to keep. ``None`` keeps every
        column in the view's schema order.
    tensor_columns : tuple of str or None, optional
        The columns to convert to tensors. ``None`` selects the numeric and
        anchor columns automatically from the Arrow schema.
    resolve_media : bool, optional
        Whether to resolve a per-row media reference through the
        :mod:`lairs.media` anchor resolver as rows are produced.
    """

    columns: tuple[str, ...] | None = dx.field(
        default=None,
        description="ordered subset of columns to keep, or all when unset",
    )
    tensor_columns: tuple[str, ...] | None = dx.field(
        default=None,
        description="columns to convert to tensors, or inferred when unset",
    )
    resolve_media: bool = dx.field(
        default=False,
        description="whether to resolve per-row media references",
    )


def _numeric_column_names(view: pa.Table) -> tuple[str, ...]:
    """Return the names of the numeric columns of an Arrow table, in order.

    A column is numeric when its Arrow type is an integer, floating, or boolean
    type. These are the columns that convert cleanly to a tensor without further
    encoding.

    Parameters
    ----------
    view : pyarrow.Table
        The Arrow table to inspect.

    Returns
    -------
    tuple of str
        The numeric column names, in schema order.
    """
    names: list[str] = []
    for name in view.column_names:
        field_type = view.schema.field(name).type
        if (
            pa.types.is_integer(field_type)
            or pa.types.is_floating(field_type)
            or pa.types.is_boolean(field_type)
        ):
            names.append(name)
    return tuple(names)


def _selected_columns(
    view: pa.Table,
    spec: TorchExportSpec | None,
) -> tuple[str, ...]:
    """Return the ordered columns kept for export.

    Parameters
    ----------
    view : pyarrow.Table
        The Arrow table being exported.
    spec : TorchExportSpec or None
        The export specification, or ``None`` to keep every column.

    Returns
    -------
    tuple of str
        The kept column names, in the specified (or schema) order.

    Raises
    ------
    KeyError
        When the spec names a column absent from the view.
    """
    if spec is None or spec.columns is None:
        return tuple(view.column_names)
    available = set(view.column_names)
    missing = [name for name in spec.columns if name not in available]
    if missing:
        msg = f"columns not in view: {sorted(missing)}"
        raise KeyError(msg)
    return tuple(spec.columns)


def _tensor_columns(
    view: pa.Table,
    spec: TorchExportSpec | None,
    kept: tuple[str, ...],
) -> tuple[str, ...]:
    """Return the kept columns that become tensors.

    When the spec names ``tensor_columns`` they are used (intersected with the
    kept columns, preserving the spec order); otherwise the numeric columns of
    the view are inferred and intersected with the kept columns.

    Parameters
    ----------
    view : pyarrow.Table
        The Arrow table being exported.
    spec : TorchExportSpec or None
        The export specification, or ``None`` to infer numeric columns.
    kept : tuple of str
        The columns kept for export.

    Returns
    -------
    tuple of str
        The kept columns that convert to tensors.
    """
    kept_set = set(kept)
    if spec is not None and spec.tensor_columns is not None:
        return tuple(name for name in spec.tensor_columns if name in kept_set)
    return tuple(name for name in _numeric_column_names(view) if name in kept_set)


def _row_record(
    view: pa.Table,
    index: int,
    kept: tuple[str, ...],
) -> dict[str, JsonValue]:
    """Return one row of the kept columns as a plain Python mapping.

    Parameters
    ----------
    view : pyarrow.Table
        The Arrow table to read.
    index : int
        The zero-based row index.
    kept : tuple of str
        The columns to read.

    Returns
    -------
    dict
        The row's kept-column values as native Python scalars and containers.

    Raises
    ------
    IndexError
        When ``index`` is out of range.
    """
    if index < 0 or index >= view.num_rows:
        msg = f"row index {index} out of range for {view.num_rows} rows"
        raise IndexError(msg)
    return {name: view.column(name)[index].as_py() for name in kept}


def collate_records(
    batch: list[dict[str, JsonValue]],
    tensor_columns: tuple[str, ...],
) -> dict[str, JsonValue | Tensor]:
    """Collate a batch of row mappings into a column-major batch mapping.

    Tensor columns are stacked into a single ``torch`` tensor; the remaining
    columns are collected into a list, one entry per row. The function is pure
    apart from the lazy ``torch`` import that the tensor columns require, so a
    batch with no tensor columns collates without ``torch`` installed.

    Parameters
    ----------
    batch : list of dict
        The per-row mappings to collate.
    tensor_columns : tuple of str
        The columns to stack into a tensor.

    Returns
    -------
    dict
        A column-major mapping: each tensor column maps to a stacked tensor, and
        every other column maps to a list of its per-row values.
    """
    columns: dict[str, JsonValue | Tensor] = {}
    names = list(batch[0].keys()) if batch else []
    tensor_set = set(tensor_columns)
    for name in names:
        values = [row[name] for row in batch]
        if name in tensor_set:
            columns[name] = _stack_tensor(name, values)
        else:
            columns[name] = values
    return columns


def _stack_tensor(name: str, values: list[JsonValue]) -> Tensor:
    """Stack a column of scalar values into a one-dimensional tensor.

    A tensor column must be free of nulls: ``torch.as_tensor`` cannot infer a
    dtype for a ``None`` entry and would otherwise raise an opaque framework
    error. A null is reported as a clear lairs error naming the column instead.

    Parameters
    ----------
    name : str
        The column the values belong to, used in the error message.
    values : list
        The per-row scalar values of one tensor column.

    Returns
    -------
    torch.Tensor
        A one-dimensional tensor of the column's values.

    Raises
    ------
    ValueError
        When the column carries a null value, which cannot be stacked into a
        tensor. Project the column out or fill its nulls before collating.
    """
    if any(value is None for value in values):
        msg = (
            f"tensor column {name!r} carries a null value and cannot be stacked "
            f"into a tensor; drop the column or fill its nulls before collating"
        )
        raise ValueError(msg)
    torch = _import_torch()
    return torch.as_tensor(values)


def _import_torch() -> ModuleType:
    """Import and return the ``torch`` module, or raise a clear error.

    Returns
    -------
    types.ModuleType
        The imported ``torch`` module.

    Raises
    ------
    ImportError
        When ``torch`` is not installed.
    """
    try:
        import torch  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised when torch absent
        msg = "the torch exporter requires the optional 'lairs[torch]' extra"
        raise ImportError(msg) from exc
    return torch


class TorchExportResult(dx.Model):
    """The bundle a PyTorch export produces.

    Carries the map-style dataset, the iterable-dataset variant, and the tensor
    columns the ``collate`` helper stacks. The two datasets are behavioural
    objects held in opaque fields; the tensor columns are typed metadata so a
    caller can build a ``DataLoader`` with the matching collate function.

    Attributes
    ----------
    dataset : torch.utils.data.Dataset
        The map-style dataset over the Arrow rows.
    iterable : torch.utils.data.IterableDataset
        The iterable-dataset variant over the Arrow rows.
    tensor_columns : tuple of str, optional
        The columns the collate helper stacks into tensors.
    resolve_media : bool, optional
        The recorded media-resolution intent from the export spec, for a
        downstream loader transform to act on.
    """

    dataset: Dataset[dict[str, JsonValue]] = dx.field(
        opaque=True,
        description="map-style dataset over the arrow rows",
    )
    iterable: IterableDataset[dict[str, JsonValue]] = dx.field(
        opaque=True,
        description="iterable-dataset variant over the arrow rows",
    )
    tensor_columns: tuple[str, ...] = dx.field(
        default=(),
        description="columns the collate helper stacks into tensors",
    )
    resolve_media: bool = dx.field(
        default=False,
        description="recorded media-resolution intent from the export spec",
    )

    def collate(
        self,
        batch: list[dict[str, JsonValue]],
    ) -> dict[str, JsonValue | Tensor]:
        """Collate a batch of rows, stacking the tensor columns.

        Parameters
        ----------
        batch : list of dict
            The per-row mappings to collate.

        Returns
        -------
        dict
            The column-major batch with tensor columns stacked.
        """
        return collate_records(batch, self.tensor_columns)


class TorchExporter:
    """An exporter that emits PyTorch datasets from an Arrow view.

    Binds to :class:`~lairs.integrations.ports.Exporter` with the Arrow table as
    its view, :class:`TorchExportSpec` as its specification, and
    :class:`TorchExportResult` as its return type. PyTorch is imported lazily, so
    constructing the exporter and inspecting an Arrow view never require the
    optional extra.
    """

    name = "torch"

    def export(
        self,
        view: pa.Table,
        *,
        spec: TorchExportSpec | None = None,
    ) -> TorchExportResult:
        """Export an Arrow view to a bundle of PyTorch datasets.

        Builds a map-style dataset and an iterable-dataset variant over the kept
        columns of the view, recording the tensor columns the bundled
        ``collate`` helper stacks. The datasets read rows lazily from the Arrow
        table, so no per-row tensor is built until a row is fetched.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : TorchExportSpec or None, optional
            An optional export specification (column selection, tensor columns,
            media resolution). ``None`` keeps every column and infers the tensor
            columns from the schema.

        Returns
        -------
        TorchExportResult
            The map-style dataset, the iterable variant, and the tensor columns.

        Raises
        ------
        ImportError
            When the optional ``torch`` dependency is not installed.
        KeyError
            When the spec names a column absent from the view.
        """
        kept = _selected_columns(view, spec)
        tensor_columns = _tensor_columns(view, spec, kept)
        dataset = self._build_map_dataset(view, kept)
        iterable = self._build_iterable_dataset(view, kept)
        return TorchExportResult(
            dataset=dataset,
            iterable=iterable,
            tensor_columns=tensor_columns,
            resolve_media=spec.resolve_media if spec is not None else False,
        )

    def _build_map_dataset(
        self,
        view: pa.Table,
        kept: tuple[str, ...],
    ) -> Dataset[dict[str, JsonValue]]:
        """Build a map-style dataset over the kept columns of the view.

        Parameters
        ----------
        view : pyarrow.Table
            The Arrow table to wrap.
        kept : tuple of str
            The columns each row exposes.

        Returns
        -------
        torch.utils.data.Dataset
            A map-style dataset returning one row mapping per index.
        """
        torch = _import_torch()

        class _ArrowMapDataset(torch.utils.data.Dataset):
            """A map-style dataset reading rows from an Arrow table on demand."""

            def __init__(self, table: pa.Table, columns: tuple[str, ...]) -> None:
                self._table = table
                self._columns = columns

            def __len__(self) -> int:
                return self._table.num_rows

            def __getitem__(self, index: int) -> dict[str, JsonValue]:
                return _row_record(self._table, index, self._columns)

        return _ArrowMapDataset(view, kept)

    def _build_iterable_dataset(
        self,
        view: pa.Table,
        kept: tuple[str, ...],
    ) -> IterableDataset[dict[str, JsonValue]]:
        """Build an iterable-dataset variant over the kept columns of the view.

        Parameters
        ----------
        view : pyarrow.Table
            The Arrow table to wrap.
        kept : tuple of str
            The columns each row exposes.

        Returns
        -------
        torch.utils.data.IterableDataset
            An iterable dataset yielding one row mapping at a time. Under a
            multi-worker ``DataLoader`` each worker reads a disjoint stride of
            the rows (via ``torch.utils.data.get_worker_info``), so no row is
            emitted more than once.
        """
        torch = _import_torch()

        class _ArrowIterableDataset(torch.utils.data.IterableDataset):
            """An iterable dataset streaming a worker-disjoint stride of rows."""

            def __init__(self, table: pa.Table, columns: tuple[str, ...]) -> None:
                self._table = table
                self._columns = columns

            def __iter__(self) -> Iterator[dict[str, JsonValue]]:
                worker_info = torch.utils.data.get_worker_info()
                if worker_info is None:
                    start, step = 0, 1
                else:
                    start, step = worker_info.id, worker_info.num_workers
                for index in range(start, self._table.num_rows, step):
                    yield _row_record(self._table, index, self._columns)

        return _ArrowIterableDataset(view, kept)
