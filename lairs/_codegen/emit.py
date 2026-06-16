"""Emit Python module text for generated models.

Renders didactic models built from spec dicts into committed module text with
a generated-by header and the source manifest hash.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs._types import JsonValue

__all__ = ["emit_module"]


def emit_module(
    specs: Sequence[dict[str, JsonValue]],
    *,
    manifest_hash: str,
) -> str:
    """Render model spec dicts to Python module source text.

    Parameters
    ----------
    specs : collections.abc.Sequence of dict
        The didactic spec dicts for one namespace.
    manifest_hash : str
        The content hash of the source lexicon tree, recorded in the header.

    Returns
    -------
    str
        The module source text, with a generated-by header.

    Raises
    ------
    NotImplementedError
        Always, until the codegen pipeline lands.
    """
    raise NotImplementedError
