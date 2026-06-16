"""PyTorch data-plane exporter.

Emits a ``torch.utils.data.Dataset`` from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. Requires the ``lairs[torch]``
extra at runtime; the concrete return type is bound under ``TYPE_CHECKING``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa
    from torch.utils.data import Dataset  # ty: ignore[unresolved-import]

    from lairs.data.features import Features

__all__ = ["TorchExporter"]


class TorchExporter:
    """An exporter that emits a PyTorch dataset from an Arrow view."""

    name = "torch"

    def export(
        self,
        view: pa.Table,
        *,
        spec: Features | None = None,
    ) -> Dataset[tuple[str, ...]]:
        """Export an Arrow view to a PyTorch dataset.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : lairs.data.features.Features or None, optional
            An optional feature specification.

        Returns
        -------
        torch.utils.data.Dataset
            The exported dataset.

        Raises
        ------
        NotImplementedError
            Always, until the PyTorch exporter lands.
        """
        raise NotImplementedError
