# The dataset API

This guide covers loading a corpus, taking dataset views over it, walking the
cross-reference graph with the join helpers, operating on a `Dataset`, and
reading the `Features` derived from the model field specs.

The dataset API sits over the generated record models. A `Dataset` is generic
over the model type it yields, so indexing and iteration stay precisely typed.
Rationale is in [Concepts](../concepts/), and signatures are in the
[reference](../reference/).

## Loading a corpus

`load_corpus` reads a corpus by AT-URI and builds the joined graph by
enumerating the Layers collections of the URI's authority.

```python
from lairs.atproto.pds import PdsClient
from lairs.data import load_corpus

with PdsClient("https://pds.example") as client:
    corpus = load_corpus(
        "at://did:plc:author/pub.layers.corpus.corpus/abc",
        source="pds",
        pds_client=client,
    )
```

`source` is one of `"pds"`, `"appview"`, or `"auto"`. The `pds` source reads
directly from a PDS. The `appview` and `auto` sources are not yet implemented
without an appview client and raise `NotImplementedError`. Until endpoint
discovery lands, supply an injected `pds_client`. The `cache_dir` and `revision`
parameters are reserved and not yet used. An unrecognised `source` raises
`ValueError`.

## Corpus views

A `Corpus` exposes typed `Dataset` views over the records it holds:

```python
corpus.expressions                                   # Dataset[Expression]
corpus.segmentations()                               # Dataset[Segmentation]
corpus.media()                                       # Dataset[Media]
corpus.annotation_layers()                           # Dataset[AnnotationLayer]
corpus.annotation_layers(kind="token-tag", subkind="pos")
corpus.expression_uris()                             # list[str], in pool order
```

`annotation_layers` filters by `kind` and `subkind`. Passing neither returns
every layer. The records are returned in pool order.

## Graph-aware joins

The join helpers walk the AT-URI cross-references and group related records per
expression. Each returns a `Dataset` of a join-row model.

```python
for row in corpus.with_annotations():
    print(row.uri, row.expression.text, len(row.annotation_layers))

for row in corpus.with_segmentation():
    print(row.uri, len(row.segmentations))

for row in corpus.with_media():
    print(row.uri, row.media)            # None when the media record is unloaded
```

- `with_annotations` groups annotation layers by their `expression` ref and
  attaches them to the matching expression. Expressions with no layers still
  appear, with an empty group.
- `with_segmentation` groups segmentations the same way.
- `with_media` resolves each expression's `mediaRef` through the pool. The join
  row carries `None` when the media record is not loaded.

## Operating on a `Dataset`

A `Dataset` is lazy by default. An in-memory dataset (the form the corpus views
produce) supports `len` and indexing. A streaming dataset pulls records lazily
from a factory and has neither until drained.

```python
ds = corpus.expressions

len(ds)                                  # in-memory only; raises TypeError if streaming
ds[0]                                    # in-memory only; raises TypeError if streaming
for record in ds:                        # always works
    ...

for batch in ds.iter(batch_size=32):     # tuples of records; last may be shorter
    ...
```

`map` and `filter` are lazy: they compose onto the source and run as records flow
through a later iteration or materialisation, preserving streaming behaviour.
`take(n)` and `materialize()` drain into a new in-memory dataset with random
access.

```python
tagged = ds.map(lambda e: e.with_(kind="sentence"))   # lazy, returns a Dataset
some = ds.filter(lambda e: e.text != "").take(100)     # in-memory, at most 100
```

Materialise to columnar form with `to_arrow` (the flattened view, with any
`anchor` field expanded into typed anchor columns) or `to_pandas`. pandas is an
optional dependency, and `to_pandas` raises a clear `ImportError` when it is absent.

```python
table = ds.to_arrow()                    # pyarrow.Table
frame = ds.to_pandas()                   # requires the optional pandas dependency
```

Build a streaming dataset from an iterator factory when the source is a PDS
cursor or a repository scan:

```python
from lairs.data import Dataset
from lairs.records._generated.expression import Expression

stream = Dataset.streaming(lambda: iter(fetch_expressions()), model=Expression)
stream.is_streaming                      # True
sample = stream.take(64)                 # materialises the first 64
```

## Features

`Dataset.features` returns a `Features` model derived from the dataset's model
field specs, so it always matches the lexicons. Each field becomes a
`FeatureSpec` with a name, a dtype token, and a nullability flag.

```python
features = corpus.expressions.features
features.names()                         # ("$type", "id", "kind", "text", ...)
spec = features.get("text")              # FeatureSpec or None
spec.dtype                               # "string"
spec.nullable                            # True when optional or not required
```

The dtype mapping (`features_of`, `dtype_of`) unwraps optionality, renders tuples
as `sequence<...>`, descends through `dx.Embed`, marks model-valued and tagged-
union fields as `struct`, and forces opaque fields to `binary`. A streaming or
empty dataset needs its `model` supplied so the features can be derived.
Otherwise `features` raises `ValueError`.

## See also

- [Authoring](authoring.md) for constructing the records a corpus reads.
- [Exporters](exporters.md) for turning Arrow views into framework datasets.
- [Codecs](codecs.md) for ingesting external annotation formats.
