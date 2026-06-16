"""HuggingFace ``datasets`` exporter.

Builds a ``datasets.Dataset`` straight from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. Requires the ``lairs[hf]``
extra at runtime; the concrete return type is bound under ``TYPE_CHECKING``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa
    from datasets import Dataset  # ty: ignore[unresolved-import]

    from lairs.data.features import Features

__all__ = ["HuggingFaceExporter"]


class HuggingFaceExporter:
    """An exporter that emits a ``datasets.Dataset`` from an Arrow view."""

    name = "hf"

    def export(self, view: pa.Table, *, spec: Features | None = None) -> Dataset:
        """Export an Arrow view to a HuggingFace dataset.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : lairs.data.features.Features or None, optional
            An optional feature specification (task template, columns).

        Returns
        -------
        datasets.Dataset
            The exported, Arrow-backed dataset.

        Raises
        ------
        NotImplementedError
            Always, until the HuggingFace exporter lands.
        """
        raise NotImplementedError
