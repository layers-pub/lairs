"""TensorFlow ``tf.data`` data-plane exporter.

Emits a ``tf.data.Dataset`` from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. Requires the ``lairs[tf]``
extra at runtime; the concrete return type is bound under ``TYPE_CHECKING``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa
    import tensorflow as tf  # ty: ignore[unresolved-import]

    from lairs.data.features import Features

__all__ = ["TfDataExporter"]


class TfDataExporter:
    """An exporter that emits a ``tf.data.Dataset`` from an Arrow view."""

    name = "tfdata"

    def export(
        self,
        view: pa.Table,
        *,
        spec: Features | None = None,
    ) -> tf.data.Dataset:
        """Export an Arrow view to a ``tf.data.Dataset``.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : lairs.data.features.Features or None, optional
            An optional feature specification.

        Returns
        -------
        tf.data.Dataset
            The exported dataset.

        Raises
        ------
        NotImplementedError
            Always, until the ``tf.data`` exporter lands.
        """
        raise NotImplementedError
