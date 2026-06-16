"""Generated-safe view helpers over the record models.

These helpers are behaviour over the generated models, never replacements for
them. They cover common pain points such as dispatching on which anchor a
record carries and exploding an annotation layer into rows. Anchors and layers
are passed as didactic models; the row shape is JSON-valued.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    import didactic.api as dx

    from lairs._types import JsonValue

__all__ = ["anchor_kind", "explode_layer"]


def anchor_kind(anchor: dx.Model) -> str:
    """Return the kind discriminator of an anchor model.

    Parameters
    ----------
    anchor : didactic.Model
        An ``anchor`` union instance from the generated models.

    Returns
    -------
    str
        The anchor kind (for example ``"span"`` or ``"temporalSpan"``).

    Raises
    ------
    NotImplementedError
        Always, until the codegen pipeline lands.
    """
    raise NotImplementedError


def explode_layer(layer: dx.Model) -> Iterator[dict[str, JsonValue]]:
    """Explode an annotation layer into one row per annotation.

    Parameters
    ----------
    layer : didactic.Model
        An ``annotationLayer`` model instance.

    Returns
    -------
    collections.abc.Iterator of dict
        One flattened row per annotation in the layer.

    Raises
    ------
    NotImplementedError
        Always, until the codegen pipeline lands.
    """
    raise NotImplementedError
