# Exporters: Arrow views to framework datasets

This guide covers the `Exporter` port and the bundled exporters that turn a
flattened Arrow view into a framework-native dataset: HuggingFace `datasets`, the
Hub push/pull, PyTorch, tf.data, and WebDataset. It notes which extra each needs.

An exporter consumes an Arrow view (a `pyarrow.Table`, produced by
`Dataset.to_arrow`) and emits a target-framework object. (`Corpus.materialize`
instead writes Parquet view files to disk and returns their paths, so it is not a
source for `export`.) The `Exporter`
protocol in `lairs.integrations.ports` is generic over the view, the export
specification, and the returned object. The one method is
`export(view, *, spec=None)`. Because the Arrow flattening already resolves the
polymorphic Layers anchors into typed columns, the exporters stay thin: they
project columns and hand the table over. Resolve an exporter by name:

```python
import lairs

HuggingFaceExporter = lairs.exporter("hf")
TorchExporter = lairs.exporter("torch")
TfDataExporter = lairs.exporter("tfdata")
WebDatasetExporter = lairs.exporter("webdataset")
```

An unknown name raises `UnknownAdapterError`, listing the available exporters.
Every framework dependency is imported lazily, so importing an exporter module
never pulls its extra in. The optional import surfaces only when an export runs.

## HuggingFace `datasets`

`HuggingFaceExporter` wraps the Arrow table near zero-copy into a
`datasets.Dataset`.

```python
from lairs.integrations.hf.datasets import ExportSpec, task_template_for

exporter = lairs.exporter("hf")()
ds = exporter.export(table)                              # all columns

spec = ExportSpec(shape="exploded", columns=("tokens", "labels", "token_index"))
ds = exporter.export(table, spec=spec)                  # projected
```

The `shape` is descriptive metadata, not a re-shaping step: `nested` keeps one
row per expression with annotations as sequence-valued columns, `exploded` keeps
one row per annotation. The Arrow builders produce one shape or the other.

**Task templates.** `task_template_for(kind, subkind=, formalism=)` returns the
most specific canonical HuggingFace task shape for a Layers triple (for example
`token-classification` for a `token-tag` layer, `dependency-parsing` for a
`tree`/`universal-dependencies` layer). `ExportSpec.for_template(template)`
projects that template's columns and records its task name for downstream tooling
and dataset-card provenance.

```python
template = task_template_for("token-tag", subkind="pos")
ds = exporter.export(table, spec=ExportSpec.for_template(template))
```

**Streaming.** `to_hf_iterable(source, spec=)` builds a `datasets.IterableDataset`
from a zero-argument factory returning fresh Arrow `RecordBatch` iterators, so a
large corpus trains without a full download.

**Feature schema.** `hf_features_from(features)` derives a `datasets.Features`
mapping from a lairs `Features` schema, mapping each spec to a `Value` (or a
`Sequence` of a `Value` for sequence tokens). Struct tokens degrade to a JSON
string column.

`datasets` comes from the `lairs[hf]` extra. Every method here raises a clear
`ImportError` when it is absent.

## HuggingFace Hub

`lairs.integrations.hf.hub` mirrors a corpus to the Hub as Arrow/Parquet shards
with an auto-generated dataset card carrying provenance, and reads a mirror back.
The Hub is a mirror target only. The PDS and the Repository stay canonical.

```python
from lairs.integrations.hf.hub import provenance_bundle, push_to_hub, load_from_hub

bundle = provenance_bundle(
    corpus_uri="at://did:plc:author/pub.layers.corpus.corpus/abc",
    revision="v1",
    license="CC-BY-4.0",
    name="my-corpus",
)
url = push_to_hub(table, "org/my-corpus", private=False, provenance=bundle)
ds = load_from_hub("org/my-corpus", revision="main")
```

The `ProvenanceBundle` records the corpus AT-URI, the Repository revision or tag,
the vendored lexicon manifest hash and Layers version (filled from the manifest
packaged with lairs), the license, and the corpus name. The lexicon manifest hash
and Layers version are read from the vendored manifest; the remaining fields,
including `license`, are supplied by the caller from the corpus record. The
`license` field is a plain license-identifier string the caller passes through (a
slug such as `CC-BY-4.0`, or an expression such as `MIT OR Apache-2.0`).
`dataset_card(bundle)` renders the markdown card, where only set fields appear. `push_to_hub` needs both
`datasets` and `huggingface_hub` from `lairs[hf]`, and `load_from_hub` needs
`datasets`. Each raises a clear `ImportError` when absent. Hub authentication is
the caller's responsibility (the usual `huggingface_hub` login).

## PyTorch

`TorchExporter.export` returns a `TorchExportResult` bundling a map-style
`Dataset`, an `IterableDataset` variant, and the tensor columns its `collate`
helper stacks.

```python
from lairs.integrations.torch import TorchExportSpec

exporter = lairs.exporter("torch")()
result = exporter.export(table, spec=TorchExportSpec(
    columns=("token_index", "label", "byte_start", "byte_end"),
    tensor_columns=None,                 # infer numeric/anchor columns from the schema
))
loader = DataLoader(result.dataset, batch_size=32, collate_fn=result.collate)
```

Numeric and anchor columns become tensors, and the rest pass through as Python
values. When `tensor_columns` is unset, the numeric columns are inferred from the
Arrow schema. The flat view carries no blob payloads, so media bytes are not
materialized here. `spec.resolve_media` is recorded on the result for a
downstream loader transform (which owns the media resolver) to act on. The
column-selection helpers are pure Python, but `export` always imports `torch`,
because both the map-style and iterable datasets it builds subclass
`torch.utils.data.Dataset` / `IterableDataset`. `torch` comes from the
`lairs[torch]` extra, and a missing column named in the spec raises `KeyError`.

## tf.data

`TfDataExporter.export` emits a dictionary-structured `tf.data.Dataset`, one
tensor per retained column.

```python
from lairs.integrations.tfdata import TfDataSpec, feature_specs_of

exporter = lairs.exporter("tfdata")()
ds = exporter.export(table, spec=TfDataSpec(
    columns=("tokens", "labels"),
    batch_size=64,
    shuffle_buffer=1000,
    seed=0,
    drop_remainder=True,
))
```

The Arrow-schema to feature-spec derivation is pure and tensorflow-free:
`feature_specs_of(schema, columns=)` maps each column to a `TfFeatureSpec` with a
dtype token and a list-valued flag. Only resolving those tokens to concrete
dtypes and building the dataset touch tensorflow, behind a lazy import.
tensorflow comes from the `lairs[tf]` extra (Python `< 3.14`), and `export` raises
a clear `ImportError` when it is absent.

## WebDataset

`WebDatasetExporter.export` writes tar shards for heavy media. Each row becomes
one sample: a `__key__`, a `.json` member with the row's scalar fields, and, when
a media column is set, a media member with the resolved bytes.

```python
from lairs.integrations.webdataset import WebDatasetSpec

exporter = lairs.exporter("webdataset")()
shards = exporter.export(table, spec=WebDatasetSpec(
    output_dir="out/shards",
    shard_size=1000,
    shard_prefix="train",
    key_column="uri",
    media_column="media",
))
```

A media cell that is raw bytes is embedded directly. A JSON-shaped media record
is resolved through the media resolver, whose mime type drives the member
extension. A non-positive `shard_size` or a named column absent from the view
raises `ValueError`. The tar-writing path uses the standard library, so sharding
runs without any extra. The read-back loader, `load(shards)`, requires the
optional `webdataset` library (the `lairs[webdataset]` extra) and is imported
lazily. Calling it without the library raises a clear `ImportError`.

## Extras at a glance

| Exporter | Extra | Works without the extra |
|---|---|---|
| `hf` | `lairs[hf]` (`datasets`, `huggingface_hub`) | task-template selection |
| `torch` | `lairs[torch]` (`export` always needs it) | the standalone column-selection helpers, and collate without tensor columns |
| `tfdata` | `lairs[tf]` (Python `< 3.14`) | feature-spec derivation from the schema |
| `webdataset` | `lairs[webdataset]` for read-back | tar sharding (write path) |

## See also

- [Dataset API](dataset-api.md) for producing the Arrow views these consume.
- [Tracking](tracking.md) for pinning the revision behind an export.
