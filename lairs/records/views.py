"""Generated-safe view helpers over the record models.

These helpers are behaviour over the generated models, never replacements for
them. They cover common pain points: dispatching on which anchor a record
carries and exploding an annotation layer into one flattened row per
annotation. Anchors and layers are passed as didactic models; the row shape is
JSON-valued so it feeds the Arrow materialisation directly.

Notes
-----
The Layers ``anchor`` is an object with mutually-exclusive optional reference
properties (``textSpan``, ``tokenRef``, ``temporalSpan`` and so on), not a
formal tagged union, so :func:`anchor_kind` inspects which property is set
rather than reading a discriminator. The helper is therefore tolerant of any
generated model whose set fields name the anchor variant.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    import didactic.api as dx

    from lairs._types import JsonValue

__all__ = ["anchor_kind", "explode_layer"]

# the anchor property names, in lexicon declaration priority. an anchor object
# sets exactly one of these; the first one set names the anchor kind.
_ANCHOR_PROPERTIES: tuple[str, ...] = (
    "textSpan",
    "tokenRef",
    "tokenRefSequence",
    "temporalSpan",
    "spatioTemporalAnchor",
    "pageAnchor",
    "externalTarget",
)


def anchor_kind(anchor: dx.Model) -> str:
    """Return the kind of an anchor model.

    Parameters
    ----------
    anchor : didactic.Model
        An ``anchor`` model from the generated records. Its mutually-exclusive
        optional properties name the anchor variant.

    Returns
    -------
    str
        The set anchor property name (for example ``"textSpan"`` or
        ``"temporalSpan"``), or ``"none"`` when no anchor property is set.
    """
    return _anchor_kind_of_row(_to_json(anchor))


def explode_layer(layer: dx.Model) -> Iterator[dict[str, JsonValue]]:
    """Explode an annotation layer into one row per annotation.

    Parameters
    ----------
    layer : didactic.Model
        An ``annotationLayer`` model instance. Its ``annotations`` field is the
        tuple of per-annotation models to flatten.

    Yields
    ------
    dict
        One row per annotation, carrying the annotation index, the layer's kind
        and subkind context, the resolved ``anchor_kind`` of the annotation,
        and the annotation's own dumped fields. The row is JSON-valued so it
        feeds the Arrow materialisation without further conversion.
    """
    dumped = _to_json(layer)
    if not isinstance(dumped, dict):
        return
    annotations = dumped.get("annotations")
    if not isinstance(annotations, list):
        return
    layer_kind = dumped.get("kind")
    layer_subkind = dumped.get("subkind")
    for index, annotation in enumerate(annotations):
        if not isinstance(annotation, dict):
            continue
        row: dict[str, JsonValue] = {
            "annotation_index": index,
            "layer_kind": layer_kind,
            "layer_subkind": layer_subkind,
            "anchor_kind": _anchor_kind_of_row(annotation.get("anchor")),
        }
        row.update(annotation)
        yield row


def _anchor_kind_of_row(anchor: JsonValue) -> str:
    """Return the anchor kind from a json-shaped anchor mapping."""
    if not isinstance(anchor, dict):
        return "none"
    for name in _ANCHOR_PROPERTIES:
        if anchor.get(name) is not None:
            return name
    for name in sorted(anchor):
        if anchor[name] is not None:
            return name
    return "none"


def _to_json(model: dx.Model) -> JsonValue:
    """Return a model as fully-resolved json-shaped data.

    ``model_dump`` is shallow: embedded models stay as model instances. Routing
    through ``model_dump_json`` resolves the whole tree (including embeds,
    unions, datetimes, and tuples) to plain json values, which is the shape the
    Arrow materialisation and the view rows expect.
    """
    return json.loads(model.model_dump_json())
