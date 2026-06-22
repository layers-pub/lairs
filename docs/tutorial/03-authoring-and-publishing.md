# Authoring and publishing

This chapter rebuilds the running example from scratch: a part-of-speech layer
over an expression, anchored by byte span. You stage the records into a local
store, commit them as a snapshot, and compute the plan to publish that snapshot
to a PDS, without sending anything.

Two facts govern the write path. Writes target only the authenticated user's own
repository, so lairs never writes to another account's records. A dry-run
publish returns the full plan for inspection before any write leaves the machine.

## Anchors

An anchor says how an annotation attaches to the source data. The builders in
`lairs.author.builders` construct the correct anchor sub-model and validate their
arguments against the lexicon constraints at construction time, raising
`BuildError` rather than deferring to a PDS rejection.

For text, the byte-span builder takes UTF-8 byte offsets:

```python
from lairs.author.builders import span

anchor = span(0, 3)
anchor.textSpan.byteStart    # 0
anchor.textSpan.byteEnd      # 3
```

The argument order and ranges are checked: a negative offset, or an end before
the start, raises `BuildError`. The other builders follow the same pattern:
`token_ref` for a token reference, `temporal` for a millisecond time span, and
`bbox` / `keyframe` / `spatio_temporal` for spatial and spatio-temporal anchors.

## An annotation layer

`LayerBuilder` assembles an annotation layer over one expression. It takes the
expression's AT-URI, the layer `kind`, and a creation timestamp. `add` appends
an annotation, minting a UUID for each one that lacks it, and `build` finalizes
the layer:

```python
from datetime import datetime, timezone

from lairs.author.builders import LayerBuilder, span

expr_uri = "at://did:plc:zf3l5xq2example/pub.layers.expression.expression/abc123"

builder = LayerBuilder(
    expr_uri,
    "token-tag",
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    subkind="pos",
)
builder.add(anchor=span(0, 3), label="DET", token_index=0)
builder.add(anchor=span(4, 7), label="NOUN", token_index=1)
layer = builder.build()

layer.kind                      # 'token-tag'
len(layer.annotations)          # 2
layer.annotations[0].label      # 'DET'
```

`kind` and `subkind` are validated against the generated model's open
vocabulary. The vocabulary is open, so a community value outside the published
set is accepted. Only an empty string is rejected. A layer must hold at least one
annotation, so calling `build` with none raises `BuildError`.

## Staging into a store

The store is a [`Repository`](../guide/store.md): a content-addressed,
git-like store where a corpus snapshot is a commit. Initialize one on disk, stage
each record under its AT-URI with `save`, and commit:

```python
import json
from pathlib import Path

from lairs.records._generated.expression import Expression
from lairs.store.repository import Repository

expression = Expression.model_validate_json(
    json.dumps(
        {
            "id": "doc-0001",
            "kind": "sentence",
            "createdAt": "2026-01-01T00:00:00Z",
            "text": "The cat sat on the mat.",
        },
    ),
)

layer_uri = "at://did:plc:zf3l5xq2example/pub.layers.annotation.annotationLayer/lay123"

repo = Repository.init(Path("store"))
repo.save(expr_uri, expression)
repo.save(layer_uri, layer)
revision = repo.commit("author a cats corpus")

repo.staged_uris()
# ['at://.../pub.layers.annotation.annotationLayer/lay123',
#  'at://.../pub.layers.expression.expression/abc123']
```

`commit` returns a revision identifier. That revision pins the exact record
values, so it is reproducible: you can read them back, tag the revision as a
named dataset version with `repo.tag(...)`, or diff two revisions.

Note that the expression record is constructed through `model_validate_json`. The
generated models coerce formatted scalars such as the `createdAt` datetime from
their JSON string form on that path, which the keyword constructor does not do.

## Planning the publish

`publish` maps a local revision to the minimal set of writes that would make a
PDS match it, by diffing the revision against what is already on the PDS by
AT-URI and content. With `dry_run=True` it computes and returns that plan and
sends nothing. With no `endpoint`, the PDS is treated as empty, so every record
in the revision becomes a create:

```python
from lairs.author.publish import publish

plan = publish(
    repo,
    revision,
    to="did:plc:zf3l5xq2example",
    dry_run=True,
)

plan.repo                   # 'did:plc:zf3l5xq2example'
plan.revision == revision   # True
plan.is_empty()             # False
len(plan.creates)           # 2
len(plan.updates)           # 0
len(plan.deletes)           # 0
```

The `to` argument is the target repository DID: the one authenticated repository
the writes would target. The plan separates `creates`, `updates`, and `deletes`,
and orders the whole write set so a referenced record always commits before its
referrer. Inspect that order with `ordered_writes`:

```python
for op in plan.ordered_writes():
    print(op.action, op.collection, op.rkey)
# create pub.layers.expression.expression abc123
# create pub.layers.annotation.annotationLayer lay123
```

The expression is created before the annotation layer that references it, because
the publisher ranks collections by cross-reference dependency. Each operation
carries the collection, the record key, the target AT-URI, and the record value,
so the dry-run plan is exactly what a live publish would send.

## From plan to live publish

A live publish drops `dry_run` and supplies the PDS `endpoint` and an
authenticated `httpx` client carrying the session's write scopes. lairs does not
implement OAuth: the authenticated client is injected, and every write is scoped
to the one repository named by `to`. With an endpoint set, the plan is diffed
against the live PDS first, so a re-publish of unchanged records is a no-op and a
re-publish of changed records upserts on a deterministic record key rather than
duplicating. That path is covered in the
[authoring and publishing guide](../guide/authoring.md). For the tutorial, the
dry run is the safe stopping point.

## What you have

You built anchors and an annotation layer with the authoring builders, staged the
records into a committed store snapshot, and computed a dependency-ordered
publish plan with a dry run that sent nothing. That closes the loop: read a
corpus, materialize its views, author new records, and plan their publication.

From here, the [Guides](../guide/index.md) cover each subsystem in depth, and the
[API reference](../reference/index.md) gives the per-symbol detail.
