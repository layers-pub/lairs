"""HuggingFace Hub push and pull.

Mirrors a corpus to the Hub as Arrow/Parquet shards with an auto-generated
dataset card carrying full provenance, and reads a mirror back. The Hub is an
export and mirror target; the PDS and Repository stay canonical. Requires the
``lairs[hf]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa
    from datasets import Dataset  # ty: ignore[unresolved-import]

__all__ = ["load_from_hub", "push_to_hub"]


def push_to_hub(view: pa.Table, repo_id: str, *, private: bool = False) -> str:
    """Push an Arrow view to the Hub with a provenance card.

    Parameters
    ----------
    view : pyarrow.Table
        The Arrow view to push.
    repo_id : str
        The target Hub dataset repository identifier.
    private : bool, optional
        Whether to create a private repository.

    Returns
    -------
    str
        The URL of the pushed dataset.

    Raises
    ------
    NotImplementedError
        Always, until the Hub integration lands.
    """
    raise NotImplementedError


def load_from_hub(repo_id: str, *, revision: str | None = None) -> Dataset:
    """Load a mirrored dataset back from the Hub.

    Parameters
    ----------
    repo_id : str
        The Hub dataset repository identifier.
    revision : str or None, optional
        A Hub revision to read.

    Returns
    -------
    datasets.Dataset
        The loaded dataset.

    Raises
    ------
    NotImplementedError
        Always, until the Hub integration lands.
    """
    raise NotImplementedError
