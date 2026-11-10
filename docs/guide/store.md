# Working with the store

The store provides an in-memory AT-URI index, an on-disk schematic
version-control repository, derived Arrow/Parquet views, and a
content-addressed blob cache. Together these support cross-reference
resolution, committed corpus snapshots, columnar access, and media-byte
deduplication.

For full signatures see the [store reference](../reference/store.md). For
the reproducibility guarantees a tagged revision provides, see
[Reproducibility](../concepts/reproducibility.md).

## Hold records in the pool

`ModelPool` keeps every loaded record indexed by its AT-URI on top of
didactic's class-indexed `ModelPool`. Add records under their URIs, look
them up, and resolve the AT-URI strings records carry as
cross-references back to instances:

```python
from lairs.store.pool import ModelPool

pool = ModelPool()
pool.add(expression_uri, expression)
pool.add(layer_uri, layer)

print(len(pool))                 # number of records
print(expression_uri in pool)    # membership by URI
same = pool.get(expression_uri)  # or None when absent
print(pool.uris())               # every AT-URI, insertion order
print(pool.models())             # every model instance, insertion order
```

`resolve` returns the target model for an AT-URI, or `None` when the target is
not loaded. A partially loaded corpus thus remains usable without raising on a
missing target. The pool walks the full JSON dump of each record to find
references, so AT-URIs nested inside embedded objects, tuples, and union members
are all discovered:

```python
target = pool.resolve(some_at_uri)   # model, or None if not loaded
outbound = pool.refs_of(layer_uri)   # AT-URIs this record points at
```

Back-references run the walk in reverse. `backrefs` returns the models
that point at a target, and `backref_uris` returns their AT-URIs. A
target that is itself absent from the pool still resolves its inbound
links, so links to a not-yet-loaded record are discoverable:

```python
referrers = pool.backrefs(expression_uri)      # list of models
referrer_uris = pool.backref_uris(expression_uri)
```

## Commit a snapshot

`Repository` wraps didactic's panproto-backed, content-addressed,
git-like VCS. Initialize a new repository or open an existing one:

```python
from pathlib import Path

from lairs.store.repository import Repository

repo = Repository.init(Path("corpus-repo"))   # create a new repository
repo = Repository.open(Path("corpus-repo"))   # reopen an existing one
```

`save` writes a record's value as JSON in the working tree under `records/`,
indexed by AT-URI, stages it as committed data keyed by that AT-URI, and stages
the record type's Model schema alongside it. `commit` captures the snapshot and
returns the revision id:

```python
repo.save(expression_uri, expression)
repo.save(layer_uri, layer)
print(repo.staged_uris())          # sorted AT-URIs in the working tree

revision = repo.commit("import ud-en")
print(repo.head())                 # current head, or None when empty
print(repo.log())                  # commit log, newest first
```

Read records back by AT-URI with `load` (validated against a Model class)
or `load_raw` (the stored JSON), each returning `None` for an unknown
URI:

```python
restored = repo.load(expression_uri, Expression)  # model, or None
raw = repo.load_raw(expression_uri)                # JsonValue, or None
```

`Workspace` groups a repository's AT-URIs by collection NSID for
per-record-type listing (`by_nsid`, `nsids`, and `uris_of(nsid)`), since
a corpus is a graph of many record types.

## Ingest in bulk

`save` stages one record per call in the per-record layout. Each call costs one
native panproto staging call, and panproto rewrites its whole staging index on
every such call, so the per-call price grows with the number of records already
staged and a loop of `save` calls is quadratic. That suits edits of a few
records, not a treebank. For many records use `save_many`, or `save_many_raw`
for records as a PDS serves them:

```python
staged = repo.save_many(
    (envelope.uri, decode(envelope, model)) for envelope in envelopes
)
staged += repo.save_many_raw(
    (envelope.uri, envelope.value) for envelope in other_envelopes
)
revision = repo.commit("pull did:plc:...")
```

Both take any iterable of `(uri, value)` pairs, consume it lazily, and return
the number of records staged. They group records by collection NSID and write
them in the packed layout, `batch_size` records per pack (4,096 by default), so
staging costs one native call per pack. Records of different types may be
interleaved in one call, several calls may precede one `commit`, and a record
staged twice keeps its later value. Neither commits: `commit` takes one snapshot
of everything staged, as after `save`.

`save_many_raw` validates nothing and stores each value exactly as given, which
is the fast path for a pull. Validating a few-kilobyte annotation layer into its
generated model and dumping it again costs several milliseconds a record, far
more than staging it, so a pull that goes model-in, model-out is capped near a
hundred records a second however fast the store is. A raw value keeps its wire
`$type`, its explicit nulls, its key order, its DAG-JSON objects such as
`{"$link": ...}`, and its numbers, including integers beyond 64 bits, so
`content_at` and `load_raw` return it unchanged and a record CID recomputed from
it matches the PDS's. A record whose collection has no generated model is stored
the same way. `load` drops the wire `$type` and rewrites blob objects before
validating a raw record, as reading from a PDS does.

`save`, `save_many`, `save_many_raw`, and `forget` may be mixed freely. A record
packed in one commit can be updated by `save` or forgotten in the next, and the
reverse; `content_at`, `diff`, `load`, and `staged_uris` see the latest write
whichever layout made it.

The figures below come from `benchmarks/store_ingest.py` on an Apple-silicon
laptop with panproto 0.74.3. Stage time includes building the synthetic records;
"rec/s" is records per second of stage plus commit. The `layer` profile mixes
annotation layers of about 10 KB of JSON (several hundred nodes, mostly null),
segmentations of about 3 KB, and sentences of about 0.4 KB; the `small` profile
uses 250-byte records the size of a UniMorph entry.

| Path | Profile | Records | Stage (s) | Commit (s) | `content_at` (s) | rec/s | Files | MB on disk |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `save`, 0.9.0 | layer | 500 | 8.72 | 0.02 | 0.46 | 57 | 1,012 | 7.4 |
| `save`, 0.9.0 | layer | 2,000 | 62.07 | 0.03 | 1.95 | 32 | 4,012 | 29.6 |
| `save` | layer | 500 | 7.46 | 0.02 | 0.21 | 67 | 1,013 | 7.4 |
| `save` | layer | 2,000 | 55.80 | 0.03 | 2.11 | 36 | 4,013 | 29.6 |
| `save_many` | layer | 5,000 | 10.16 | 0.03 | 0.35 | 491 | 15 | 2.8 |
| `save_many_raw` | layer | 5,000 | 0.49 | 0.02 | 0.25 | 9,829 | 15 | 2.3 |
| `save_many_raw` | layer | 50,000 | 5.27 | 0.05 | 2.57 | 9,392 | 37 | 23.1 |
| `save_many_raw` | small | 5,000 | 0.19 | 0.02 | 0.01 | 23,779 | 13 | 0.9 |
| `save_many_raw` | small | 50,000 | 0.78 | 0.08 | 0.25 | 57,967 | 35 | 9.0 |
| `save_many_raw` | small | 600,000 | 9.52 | 0.51 | 2.82 | 59,799 | 303 | 108.1 |

The `save_many` row validates each record into its generated model before
staging it, so most of its time is model validation and dumping, not the store.
Peak resident memory was 1.7 GB for the 50,000-record layer snapshot and 1.5 GB
for the 600,000-record small one, almost all of it the dictionary `content_at`
returns.

Packed ingestion is linear: stage, commit, and read time all grow in proportion
to the record count, and a 5,000-record pull writes about fifteen files instead
of a thousand or more. Staging is then bounded by Python's own JSON encoding of
the values, and reading by JSON decoding into the returned dictionaries, not by
panproto, whose share is a few milliseconds a pack.

## Tag and diff revisions

A tag pins the exact record values committed at a revision, giving a
reproducible named dataset version. Tag creation is on didactic's public
Repository surface, so the wrapper calls `create_tag` on the underlying
didactic handle directly:

```python
repo.tag("v1", revision=revision)   # defaults to head when revision omitted
print(repo.tags())                  # [(name, target_revision), ...]
commit_id = repo.resolve("v1")      # ref expression to commit id
```

Tagging an empty repository with no head raises `ValueError`. `resolve`
turns a branch name, tag name, or commit-id prefix into a full commit id.

There is no native revision-to-revision data diff on either surface, so
the wrapper computes the record diff itself. It reconstructs each
revision's value set by folding the committed data read with
`decoded_data_at` over the revision's commit ancestry, keyed by AT-URI,
then compares the two sets by content. `content_at(ref)` returns that value
set directly. `diff` resolves both refs (so an unknown ref fails
loudly) and returns a `RecordDiff` of the `added`, `removed`, and
`changed` AT-URIs:

```python
record_diff = repo.diff("v1", "HEAD")
print(record_diff.added, record_diff.removed, record_diff.changed)
```

`schema_diff(old, new)` is the separate structural diff over two Model
*classes* (for instance two generated record types across a Layers
version bump) and wraps `dx.diff`.

## Materialize Arrow views

Arrow/Parquet views are derived from the record store rather than treated as
canonical data. `materialize` reads the repository's records, groups them by
collection NSID, and writes one Parquet file per NSID into an output directory,
returning the written paths:

```python
from lairs.store.arrow import materialize

written = materialize(repo, Path("views"))
for path in written:
    print(path)
```

Polymorphic anchors are flattened into a fixed set of typed columns,
`ANCHOR_COLUMNS`: `anchor_kind`, `byte_start`, `byte_end`, `token_id`,
`token_index`, `t_start_ms`, `t_end_ms`, `bbox_x`, `bbox_y`, `bbox_w`,
`bbox_h`. A consumer can then filter and scan without re-dispatching the
anchor union per row. The column set is uniform across rows regardless of
which anchor variant each record uses, and unrelated columns are left
unset.

`flatten_anchor` performs this projection for a single dumped anchor,
returning a mapping over `ANCHOR_COLUMNS` with the recognised fields
filled and the rest unset; the table builders call it per row.

`records_to_table` and `expressions_table` build a table with one row per
record, anchors flattened. `annotations_table` mirrors the appview's
normalization: it explodes each layer's `annotations` array into one row
per `(layer_uri, annotation_index)`, flattening each annotation's anchor.
Pass any of these as the `views` mapping to `materialize` to write
pre-built normalized tables instead of the per-NSID default:

```python
from lairs.store.arrow import annotations_table, expressions_table, materialize

views = {
    "expressions": expressions_table(expressions),
    "annotations": annotations_table(layer_pairs),
}
materialize(repo, Path("views"), views=views)
```

## Cache blob bytes

`BlobCache` stores blob bytes on disk under `blobs/<cid>`, keyed by
content identifier. The CID is the file name, so identical content under
the same CID is deduplicated and `put` is idempotent:

```python
from lairs.store.blobcache import BlobCache

cache = BlobCache(Path("cache"))
if not cache.exists(cid):
    cache.put(cid, blob.data)
data = cache.get(cid)                 # bytes, or None when absent
target = cache.path_for(cid)          # path whether or not present
```

`path_for` returns the on-disk path whether or not the blob is present,
so the media layer can stream bytes straight to it. This cache satisfies
the `BlobCache` port the [media](media.md) layer resolves through.

## See also

- [Store reference](../reference/store.md) for full pool, repository,
  Arrow, and cache signatures.
- [Reproducibility](../concepts/reproducibility.md) for the snapshot-as-commit model and
  reproducibility guarantees.
- [Resolving and slicing media](media.md) for using the blob cache as a
  media resolution port.
