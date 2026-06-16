"""Arrow/Parquet materialized views over the record store.

Derived, rebuildable columnar views for ML-speed access, with anchors
flattened into typed columns. These views are never the source of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    import didactic.api as dx
    import pyarrow as pa

__all__ = ["materialize", "records_to_table"]


def records_to_table(records: Iterable[dx.Model]) -> pa.Table:
    """Flatten a sequence of records into an Arrow table.

    Parameters
    ----------
    records : collections.abc.Iterable of didactic.Model
        The records to flatten; anchors become typed columns.

    Returns
    -------
    pyarrow.Table
        The flattened columnar view.

    Raises
    ------
    NotImplementedError
        Always, until the store layer lands.
    """
    raise NotImplementedError


def materialize(repo_path: Path, out_dir: Path) -> list[Path]:
    """Materialize a Repository into Parquet view files.

    Parameters
    ----------
    repo_path : pathlib.Path
        The on-disk Repository to read from.
    out_dir : pathlib.Path
        The output directory for the Parquet views.

    Returns
    -------
    list of pathlib.Path
        The written view files.

    Raises
    ------
    NotImplementedError
        Always, until the store layer lands.
    """
    raise NotImplementedError
