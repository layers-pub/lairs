"""WebDataset data-plane exporter.

Emits tar shards for heavy media from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. Requires the
``lairs[webdataset]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pyarrow as pa

    from lairs.data.features import Features

__all__ = ["WebDatasetExporter"]


class WebDatasetExporter:
    """An exporter that emits WebDataset tar shards from an Arrow view."""

    name = "webdataset"

    def export(
        self,
        view: pa.Table,
        *,
        spec: Features | None = None,
    ) -> list[Path]:
        """Export an Arrow view to WebDataset tar shards.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : lairs.data.features.Features or None, optional
            An optional feature specification.

        Returns
        -------
        list of pathlib.Path
            The written tar shard files.

        Raises
        ------
        NotImplementedError
            Always, until the WebDataset exporter lands.
        """
        raise NotImplementedError
