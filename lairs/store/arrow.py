"""Arrow/Parquet materialized views over the record store.

Derived, rebuildable columnar views for ML-speed access, with anchors flattened
into typed columns. These views are never the source of truth: they are computed
from the record store and can always be regenerated with :func:`materialize`.

The flattening is driven by generic model field access (``model_dump``), so it
works against the abstract :class:`didactic.api.Model` interface today and
against the real generated record models once they land. Polymorphic anchors are
resolved into a fixed set of typed columns (``anchor_kind``, ``byte_start``,
``byte_end``, ``token_id``, ``token_index``, ``t_start_ms``, ``t_end_ms``,
``bbox_x``, ``bbox_y``, ``bbox_w``, ``bbox_h``) so a consumer can filter and
scan without re-dispatching the union per row.

The view set mirrors the appview's normalization: an ``expressions`` table (one
row per expression), an ``annotations`` table (one row per
``(layer_uri, annotation_index)`` produced by exploding each layer's
``annotations`` array), plus ``segmentations``, ``media``, and ``edges`` tables.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from lairs._types import JsonValue
    from lairs.store.repository import Repository

__all__ = [
    "ANCHOR_COLUMNS",
    "RecordLike",
    "annotations_table",
    "expressions_table",
    "flatten_anchor",
    "materialize",
    "records_to_table",
]

# the fixed set of typed anchor columns every flattened anchor expands into.
ANCHOR_COLUMNS: tuple[str, ...] = (
    "anchor_kind",
    "byte_start",
    "byte_end",
    "token_id",
    "token_index",
    "t_start_ms",
    "t_end_ms",
    "bbox_x",
    "bbox_y",
    "bbox_w",
    "bbox_h",
)


@runtime_checkable
class RecordLike(Protocol):
    """The minimal record shape the Arrow views consume.

    Any :class:`didactic.api.Model` satisfies this protocol; the views never
    depend on a concrete generated type, only on the ability to dump a record to
    a JSON string. The JSON form is used (rather than the shallow ``model_dump``)
    so nested models, tuples, and union members all normalise to plain JSON
    containers that the flattening can descend into uniformly.
    """

    def model_dump_json(self) -> str:
        """Return the record's fields as a JSON string."""
        ...


def _dumped(record: RecordLike) -> dict[str, JsonValue]:
    """Return a fully-recursive JSON-shaped dump of a record.

    Parameters
    ----------
    record : RecordLike
        The record to dump.

    Returns
    -------
    dict
        The record's fields as nested JSON-shaped containers and scalars.
    """
    decoded: dict[str, JsonValue] = json.loads(record.model_dump_json())
    return decoded


def _empty_anchor() -> dict[str, JsonValue]:
    """Return the typed anchor columns with every value unset (``None``)."""
    return dict.fromkeys(ANCHOR_COLUMNS)


def _coerce_int(value: JsonValue) -> int | None:
    """Return ``value`` as an int when it is numeric, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


_ANCHOR_VARIANT_FIELDS = (
    "textSpan",
    "tokenRef",
    "tokenRefSequence",
    "temporalSpan",
    "spatioTemporalAnchor",
    "pageAnchor",
    "externalTarget",
)
"""The optional variant fields of the ``anchor`` object, in dispatch order."""


def _anchor_body(anchor: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """Return the populated variant of an anchor wrapper, or the anchor itself.

    The ``anchor`` object dumps all of its optional variant fields with exactly
    one populated. When the mapping is that wrapper, the populated variant
    sub-object is returned. A bare variant object, or a single-key wrapper, is
    returned unchanged for the caller to classify by the fields it carries.

    Parameters
    ----------
    anchor : collections.abc.Mapping
        A dumped anchor value.

    Returns
    -------
    collections.abc.Mapping
        The variant sub-object to classify into typed columns.
    """
    if set(anchor) <= set(_ANCHOR_VARIANT_FIELDS):
        for name in _ANCHOR_VARIANT_FIELDS:
            value = anchor.get(name)
            if isinstance(value, dict):
                return value
        return anchor
    if len(anchor) == 1:
        (only_value,) = anchor.values()
        if isinstance(only_value, dict):
            return only_value
    return anchor


def flatten_anchor(anchor: Mapping[str, JsonValue] | None) -> dict[str, JsonValue]:
    """Flatten a polymorphic anchor mapping into typed columns.

    Recognises the Layers anchor variants by the fields they carry and projects
    each into the fixed :data:`ANCHOR_COLUMNS`, leaving unrelated columns unset.
    Unknown or absent anchors yield an all-``None`` row with an ``anchor_kind``
    of ``None``, so the resulting column set is uniform across rows regardless of
    which anchor variant each record uses.

    Parameters
    ----------
    anchor : collections.abc.Mapping or None
        A dumped anchor value, or ``None`` when the record has no anchor.

    Returns
    -------
    dict
        A mapping over :data:`ANCHOR_COLUMNS` with the recognised fields filled.
    """
    columns = _empty_anchor()
    if anchor is None:
        return columns
    body = _anchor_body(anchor)

    if "byteStart" in body or "byteEnd" in body:
        columns["anchor_kind"] = "span"
        columns["byte_start"] = _coerce_int(body.get("byteStart"))
        columns["byte_end"] = _coerce_int(body.get("byteEnd"))
    elif "tokenIndex" in body or "tokenizationId" in body:
        columns["anchor_kind"] = "tokenRef"
        token_id = body.get("tokenizationId")
        columns["token_id"] = token_id if isinstance(token_id, str) else None
        columns["token_index"] = _coerce_int(body.get("tokenIndex"))
    elif "start" in body or "ending" in body:
        columns["anchor_kind"] = "temporalSpan"
        columns["t_start_ms"] = _coerce_int(body.get("start"))
        columns["t_end_ms"] = _coerce_int(body.get("ending"))
    elif {"x", "y", "w", "h"} & set(body):
        columns["anchor_kind"] = "boundingBox"
        columns["bbox_x"] = _coerce_int(body.get("x"))
        columns["bbox_y"] = _coerce_int(body.get("y"))
        columns["bbox_w"] = _coerce_int(body.get("w"))
        columns["bbox_h"] = _coerce_int(body.get("h"))
    elif "temporalSpan" in body or "keyframe" in body:
        columns["anchor_kind"] = "spatioTemporalAnchor"
        span = body.get("temporalSpan")
        if isinstance(span, dict):
            columns["t_start_ms"] = _coerce_int(span.get("start"))
            columns["t_end_ms"] = _coerce_int(span.get("ending"))
    return columns


def _scalar_columns(dumped: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Return the scalar (non-container) fields of a dumped record.

    Parameters
    ----------
    dumped : collections.abc.Mapping
        A dumped record value.

    Returns
    -------
    dict
        The fields whose values are JSON scalars, suitable as flat columns.
    """
    return {
        name: value
        for name, value in dumped.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def records_to_table(records: Iterable[RecordLike]) -> pa.Table:
    """Flatten a sequence of records into an Arrow table.

    Each record's scalar fields become columns, and any ``anchor`` field is
    expanded into the typed :data:`ANCHOR_COLUMNS`. The column union across all
    records is used, with missing values filled as ``None``, so heterogeneous
    records share one schema.

    Parameters
    ----------
    records : collections.abc.Iterable of RecordLike
        The records to flatten; anchors become typed columns.

    Returns
    -------
    pyarrow.Table
        The flattened columnar view.
    """
    rows: list[dict[str, JsonValue]] = []
    for record in records:
        dumped = _dumped(record)
        row = _scalar_columns(dumped)
        anchor = dumped.get("anchor")
        anchor_map = anchor if isinstance(anchor, dict) else None
        row.update(flatten_anchor(anchor_map))
        rows.append(row)
    return _rows_to_table(rows)


def expressions_table(records: Iterable[RecordLike]) -> pa.Table:
    """Build the expressions view: one row per expression record.

    Parameters
    ----------
    records : collections.abc.Iterable of RecordLike
        The expression records.

    Returns
    -------
    pyarrow.Table
        One row per expression, anchors flattened into typed columns.
    """
    return records_to_table(records)


def annotations_table(
    layers: Iterable[tuple[str, RecordLike]],
) -> pa.Table:
    """Build the annotations view by exploding each layer's annotations array.

    Produces one row per ``(layer_uri, annotation_index)``, mirroring the
    appview's PG normalization. Each annotation's scalar fields become columns,
    its ``anchor`` is flattened into the typed columns, and ``layer_uri`` plus
    ``annotation_index`` identify the source.

    Parameters
    ----------
    layers : collections.abc.Iterable of (str, RecordLike)
        Pairs of layer AT-URI and the layer record. The record is expected to
        carry an ``annotations`` array; layers without one contribute no rows.

    Returns
    -------
    pyarrow.Table
        One row per exploded annotation.
    """
    rows: list[dict[str, JsonValue]] = []
    for layer_uri, layer in layers:
        dumped = _dumped(layer)
        annotations = dumped.get("annotations")
        if not isinstance(annotations, list):
            continue
        for index, annotation in enumerate(annotations):
            row: dict[str, JsonValue] = {
                "layer_uri": layer_uri,
                "annotation_index": index,
            }
            if isinstance(annotation, dict):
                row.update(_scalar_columns(annotation))
                anchor = annotation.get("anchor")
                anchor_map = anchor if isinstance(anchor, dict) else None
                row.update(flatten_anchor(anchor_map))
            else:
                row.update(_empty_anchor())
            rows.append(row)
    return _rows_to_table(rows)


def _rows_to_table(rows: Sequence[Mapping[str, JsonValue]]) -> pa.Table:
    """Assemble row mappings into an Arrow table over their column union.

    Parameters
    ----------
    rows : collections.abc.Sequence of collections.abc.Mapping
        The row mappings to assemble.

    Returns
    -------
    pyarrow.Table
        A table whose columns are the union of the row keys, with absent values
        filled as ``None``. An empty input yields an empty table.
    """
    if not rows:
        return pa.table({})
    columns: dict[str, None] = {}
    for row in rows:
        for key in row:
            columns.setdefault(key, None)
    data: dict[str, list[JsonValue]] = {
        column: [row.get(column) for row in rows] for column in columns
    }
    return pa.table(data)


def materialize(
    repo: Repository,
    out_dir: Path,
    *,
    views: Mapping[str, pa.Table] | None = None,
) -> list[Path]:
    """Materialize named Arrow views into Parquet files.

    The views are derived, rebuildable outputs and never the source of truth.
    When ``views`` is omitted the repository's record store is read and grouped
    by collection NSID, with each NSID written as its own Parquet file; callers
    that have already built the normalized ``expressions`` / ``annotations`` /
    ``segmentations`` / ``media`` / ``edges`` tables can pass them explicitly.

    Parameters
    ----------
    repo : Repository
        The repository whose record store is materialized when ``views`` is not
        supplied.
    out_dir : pathlib.Path
        The output directory for the Parquet views; created if absent.
    views : collections.abc.Mapping of str to pyarrow.Table or None, optional
        Pre-built named views to write. When ``None`` the views are derived from
        the repository working tree.

    Returns
    -------
    list of pathlib.Path
        The written Parquet files, in name order.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = views if views is not None else _views_from_repo(repo)
    written: list[Path] = []
    for name in sorted(resolved):
        target = out_dir / f"{name}.parquet"
        pq.write_table(resolved[name], target)
        written.append(target)
    return written


def _views_from_repo(repo: Repository) -> dict[str, pa.Table]:
    """Derive a per-NSID raw-record table set from a repository working tree.

    Parameters
    ----------
    repo : Repository
        The repository to read.

    Returns
    -------
    dict of str to pyarrow.Table
        A mapping from a sanitized NSID view name to its raw-record table. Each
        table holds the scalar fields plus flattened anchor columns of the
        records of that collection.
    """
    grouped: dict[str, list[dict[str, JsonValue]]] = {}
    for uri in repo.staged_uris():
        raw = repo.load_raw(uri)
        if not isinstance(raw, dict):
            continue
        nsid = _view_name(uri)
        row = _scalar_columns(raw)
        anchor = raw.get("anchor")
        anchor_map = anchor if isinstance(anchor, dict) else None
        row.update(flatten_anchor(anchor_map))
        row["uri"] = uri
        grouped.setdefault(nsid, []).append(row)
    return {name: _rows_to_table(rows) for name, rows in grouped.items()}


def _view_name(uri: str) -> str:
    """Return a sanitized view name derived from an AT-URI collection NSID."""
    body = uri.removeprefix("at://")
    parts = body.split("/")
    minimum_parts_with_collection = 2
    nsid = parts[1] if len(parts) >= minimum_parts_with_collection else "records"
    return nsid.replace(".", "_") or "records"
