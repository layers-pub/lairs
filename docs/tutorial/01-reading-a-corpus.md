# Reading a corpus

A corpus is a graph of `pub.layers.*` records joined by AT-URI. Loading one
enumerates the relevant collections of the AT-URI's authority, decodes each
record against its generated model, and groups the results so that an
expression's annotation layers, segmentations, and media resolve to model
instances. This chapter loads the running example, inspects its expressions, and
reads the fields off a generated `Expression` model.

## Loading

The loader is `load_corpus`. It takes the AT-URI of a corpus record. The
authority embedded in that URI is the repository whose collections are
enumerated.

```python
import lairs

uri = "at://did:plc:zf3l5xq2example/pub.layers.corpus.corpus/cats-en"
corpus = lairs.load_corpus(uri, source="pds", pds_client=client)
```

Two things about that call.

First, `load_corpus` is re-exported at the top of the `lairs` package, so
`lairs.load_corpus` and `from lairs.data import load_corpus` name the same
function. Either import works.

Second, the `pds` source reads directly from a PDS. It currently requires an
injected `pds_client`: appview-based and endpoint-discovering loads are not yet
implemented, and `load_corpus` raises `NotImplementedError` when asked to load
without a client. Public reads themselves need no authentication. The client is
injected so the loader has a transport to read through. For a live read, build a
[`PdsClient`](../reference/atproto.md) against the authority's PDS endpoint and
pass it as `pds_client`.

## Driving the loader without the network

To run this chapter offline, supply a client that returns canned record
envelopes. The loader only calls one method on the client, `list_records(repo,
collection)`, which yields `RecordEnvelope` values, so a small stand-in is
enough:

```python
from lairs.atproto.pds import RecordEnvelope
from lairs.data import load_corpus

did = "did:plc:zf3l5xq2example"
expr_uri = f"at://{did}/pub.layers.expression.expression/abc123"
layer_uri = f"at://{did}/pub.layers.annotation.annotationLayer/lay123"

records = {
    "pub.layers.expression.expression": [
        RecordEnvelope(
            uri=expr_uri,
            cid="bafyexpr",
            value={
                "id": "doc-0001",
                "kind": "sentence",
                "createdAt": "2026-01-01T00:00:00Z",
                "language": "en",
                "text": "The cat sat on the mat.",
                "anchor": {"textSpan": {"byteStart": 0, "byteEnd": 23}},
            },
        ),
    ],
    "pub.layers.annotation.annotationLayer": [
        RecordEnvelope(
            uri=layer_uri,
            cid="bafylayer",
            value={
                "expression": expr_uri,
                "kind": "token-tag",
                "subkind": "pos",
                "createdAt": "2026-01-01T00:00:00Z",
                "annotations": [
                    {
                        "uuid": {"value": "11111111-1111-4111-8111-111111111111"},
                        "label": "DET",
                        "tokenIndex": 0,
                        "anchor": {"textSpan": {"byteStart": 0, "byteEnd": 3}},
                    },
                    {
                        "uuid": {"value": "22222222-2222-4222-8222-222222222222"},
                        "label": "NOUN",
                        "tokenIndex": 1,
                        "anchor": {"textSpan": {"byteStart": 4, "byteEnd": 7}},
                    },
                ],
            },
        ),
    ],
}


class CannedClient:
    """A read client that yields fixed envelopes by collection."""

    def list_records(self, repo, collection, *, limit=None, cursor=None):
        yield from records.get(collection, [])


corpus = load_corpus(expr_uri, source="pds", pds_client=CannedClient())
```

The loader decodes each envelope's value against the generated model for its
collection. Values that fail to validate, and collections that are not Layers
record types, are dropped rather than raising, so a single malformed record does
not abort the load.

## The expressions dataset

`corpus.expressions` is a [`Dataset`](../guide/dataset-api.md) of
`Expression` models. The dataset is in-memory here, so it has a length and
supports indexing:

```python
expressions = corpus.expressions
len(expressions)        # 1
first = expressions[0]
```

Iterate it one record at a time, or in batches:

```python
for expression in expressions:
    print(expression.id, expression.kind)

for batch in expressions.iter(batch_size=32):
    print(len(batch))
```

The dataset also reports the schema it derives from the model:

```python
expressions.features.names()
# ('anchor', 'createdAt', 'eprintRef', 'features', 'id', 'kind', ...)
```

## Reading a generated Expression

Each record is an instance of the generated `Expression` model. The generated
classes live under `lairs.records._generated.<namespace>`, and the namespace
modules are also reachable as attributes of `lairs.records`. Both of these name
the same class:

```python
from lairs.records._generated.expression import Expression
from lairs.records import expression

Expression is expression.Expression        # True
```

These models are generated from the Layers lexicons and must not be hand-edited.
Their fields are read by attribute access:

```python
first = expressions[0]
first.id            # 'doc-0001'
first.kind          # 'sentence'
first.language      # 'en'
first.text          # 'The cat sat on the mat.'
```

`Expression` carries an optional `anchor` describing how the expression attaches
to its parent, plus reference fields that point at other records by AT-URI
(`mediaRef`, `parentRef`, `eprintRef`, `sourceRef`). Fields that were absent in
the record value take their declared default, and optional fields default to
`None`:

```python
first.mediaRef      # None
first.parentRef     # None
first.anchor        # Anchor(..., textSpan=Span(byteStart=0, byteEnd=23, ...), ...)
```

The `anchor` is itself a model. Its `textSpan` field carries the byte span:

```python
first.anchor.textSpan.byteStart     # 0
first.anchor.textSpan.byteEnd       # 23
```

## Joining to annotations

The corpus resolves the cross-references between records. An annotation layer
carries the AT-URI of the expression it annotates. `corpus.with_annotations()`
groups the layers by that reference and attaches them to the matching
expression. The result is a dataset of join rows, one per expression:

```python
joined = corpus.with_annotations()
row = joined[0]
row.uri                         # the expression AT-URI
row.expression.text            # 'The cat sat on the mat.'
len(row.annotation_layers)     # 1
row.annotation_layers[0].kind  # 'token-tag'
```

An expression with no layers still appears, with an empty `annotation_layers`.
The same pattern resolves the other relations: `with_segmentation()` groups
segmentations by their target expression, and `with_media()` resolves each
expression's `mediaRef` to its media record when that record is loaded.

## What you have

You loaded a corpus from a PDS read client, indexed and iterated its expressions
dataset, read the fields off a generated `Expression` model and its `anchor`, and
joined expressions to their annotation layers. The next chapter turns these
records into columnar Arrow and Parquet views.

[Next: materialising views](02-materialising-views.md).
