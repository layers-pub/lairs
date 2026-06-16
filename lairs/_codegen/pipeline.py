"""Top-level codegen pipeline.

Drives lexicon JSON through panproto parsing, the Schema-to-spec mapping,
didactic model building, and module emission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["check", "generate"]


def generate(lexicon_root: Path, out_root: Path) -> list[Path]:
    """Generate model modules from a vendored lexicon tree.

    Parameters
    ----------
    lexicon_root : pathlib.Path
        The root of the vendored ``pub/layers`` lexicon tree.
    out_root : pathlib.Path
        The output directory for emitted model modules.

    Returns
    -------
    list of pathlib.Path
        The paths of the generated module files.

    Raises
    ------
    NotImplementedError
        Always, until the codegen pipeline lands.
    """
    raise NotImplementedError


def check(lexicon_root: Path, out_root: Path) -> bool:
    """Check whether committed modules are stale relative to the lexicons.

    Parameters
    ----------
    lexicon_root : pathlib.Path
        The root of the vendored lexicon tree.
    out_root : pathlib.Path
        The directory holding the committed generated modules.

    Returns
    -------
    bool
        ``True`` if the committed modules match a fresh generation.

    Raises
    ------
    NotImplementedError
        Always, until the codegen pipeline lands.
    """
    raise NotImplementedError
