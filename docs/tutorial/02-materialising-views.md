# Materialising views

The records you read in the last chapter are the source of truth. For
ML-speed scanning and filtering you want them flattened into columns. lairs
materialises the record graph into Arrow tables and Parquet files: an
`expressions` view with one row per expression, and an `annotations` view with
one row per annotation. These views are derived and rebuildable. They are never
authoritative, and you can always regenerate them from the records.

This chapter starts from the `corpus` built in the
[previous chapter](01-reading-a-corpus.md).

## Materialising to Parquet

`Corpus.materialize` builds the normalised views from the graph and writes one
Parquet file per view into a directory, returning the written paths in name
order:

```python
from pathlib import Path

paths = corpus.materialize(Path("views"))
[p.name for p in paths]
# ['annotations.parquet', 'expressions.parquet']
```

Read a view back with pyarrow:

```python
import pyarrow.parquet as pq

annotations = pq.read_table("views/annotations.parquet")
annotations.column_names
# ['layer_uri', 'annotation_index', 'confidence', ..., 'label', 'tokenIndex',
#  ..., 'anchor_kind', 'byte_start', 'byte_end', 'token_id', 'token_index', ...]
```

The annotations view is produced by exploding each layer's `annotations` array:
one row per annotation, identified by the layer's AT-URI in `layer_uri` and the
annotation's position in `annotation_index`. The annotation's scalar fields
become their own columns:

```python
annotations.column("layer_uri").to_pylist()
# ['at://.../pub.layers.annotation.annotationLayer/lay123',
#  'at://.../pub.layers.annotation.annotationLayer/lay123']
annotations.column("annotation_index").to_pylist()   # [0, 1]
annotations.column("label").to_pylist()              # ['DET', 'NOUN']
annotations.column("tokenIndex").to_pylist()         # [0, 1]
```

## The dataset to an Arrow table

You do not have to go through Parquet. Any [`Dataset`](../guide/dataset-api.md)
materialises straight to an in-memory Arrow table with `to_arrow()`:

```python
table = corpus.expressions.to_arrow()
table.num_rows                  # 1
table.column("text").to_pylist()       # ['The cat sat on the mat.']
table.column("kind").to_pylist()       # ['sentence']
```

`to_arrow` produces the same flattened columnar view the Parquet path writes:
scalar fields become columns and the column set is the union across all records,
with missing values filled as null so heterogeneous records share one schema.

## The flattened anchor columns

A record's anchor is polymorphic: it may be a byte span, a token reference, a
temporal span, a bounding box, or a spatio-temporal anchor. Rather than leave a
union in the table, the flattening expands every anchor into a fixed set of typed
columns, so a consumer filters and scans without re-dispatching the union per
row. The column set is exposed as a constant:

```python
from lairs.store.arrow import ANCHOR_COLUMNS

ANCHOR_COLUMNS
# ('anchor_kind', 'byte_start', 'byte_end', 'token_id', 'token_index',
#  't_start_ms', 't_end_ms', 'bbox_x', 'bbox_y', 'bbox_w', 'bbox_h')
```

Every flattened table carries all of these columns. `anchor_kind` names the
anchor variant. The remaining columns hold the variant's coordinates, with the
columns that do not apply to a given row left null. A byte-span anchor fills
`byte_start` and `byte_end`. A token reference fills `token_id` and
`token_index`. A temporal span fills `t_start_ms` and `t_end_ms`. A bounding box
fills the four `bbox_*` columns.

For token-level annotation rows, the authoritative token position is the
annotation's own `tokenIndex` column shown above, which the explode emits
directly from the annotation's scalar field.

## What you have

You materialised a corpus to Parquet, read a view back with pyarrow, turned a
dataset directly into an Arrow table, and saw the fixed anchor columns every
flattened view carries. The next chapter goes the other direction: building
records and computing a plan to publish them.

[Next: authoring and publishing](03-authoring-and-publishing.md).
