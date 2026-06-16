"""Console entry point for lairs.

Exposes the ``lairs`` command for vendoring lexicons, regenerating models,
pulling and materializing corpora, publishing, and inspecting records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the lairs command-line interface.

    Parameters
    ----------
    argv : collections.abc.Sequence of str or None, optional
        The argument vector, excluding the program name; defaults to the
        process arguments.

    Returns
    -------
    int
        The process exit code.

    Raises
    ------
    NotImplementedError
        Always, until the command-line interface lands.
    """
    raise NotImplementedError
