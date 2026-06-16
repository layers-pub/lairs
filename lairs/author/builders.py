"""Ergonomic anchor, layer, and record builders over the generated models.

These builders are behaviour over the generated models, not replacements for
them; authoring is validated against the lexicons by construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    import didactic.api as dx

__all__ = ["bbox", "span", "spatio_temporal", "temporal", "token_ref"]


def span(byte_start: int, byte_end: int) -> dx.Model:
    """Build a byte-span anchor.

    Parameters
    ----------
    byte_start : int
        The UTF-8 byte start offset (inclusive).
    byte_end : int
        The UTF-8 byte end offset (exclusive).

    Returns
    -------
    didactic.Model
        The ``span`` anchor union variant.

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError


def token_ref(tokenization_id: str, token_index: int) -> dx.Model:
    """Build a token-reference anchor.

    Parameters
    ----------
    tokenization_id : str
        The tokenization UUID the index refers into.
    token_index : int
        The zero-based token index.

    Returns
    -------
    didactic.Model
        The ``tokenRef`` anchor union variant.

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError


def temporal(start_ms: int, end_ms: int) -> dx.Model:
    """Build a temporal-span anchor.

    Parameters
    ----------
    start_ms : int
        The start offset in milliseconds.
    end_ms : int
        The end offset in milliseconds.

    Returns
    -------
    didactic.Model
        The ``temporalSpan`` anchor union variant.

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError


def bbox(x: float, y: float, width: float, height: float) -> dx.Model:
    """Build a bounding-box anchor.

    Parameters
    ----------
    x : float
        The left coordinate in pixels.
    y : float
        The top coordinate in pixels.
    width : float
        The box width in pixels.
    height : float
        The box height in pixels.

    Returns
    -------
    didactic.Model
        The ``boundingBox`` anchor union variant.

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError


def spatio_temporal(
    temporal_span: dx.Model,
    keyframes: Sequence[dx.Model],
    interpolation: str,
) -> dx.Model:
    """Build a spatio-temporal anchor.

    Parameters
    ----------
    temporal_span : didactic.Model
        The temporal span the keyframes range over.
    keyframes : collections.abc.Sequence of didactic.Model
        The keyframe boxes.
    interpolation : str
        The interpolation mode (``linear``, ``step``, or ``cubic``).

    Returns
    -------
    didactic.Model
        The ``spatioTemporalAnchor`` union variant.

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError
