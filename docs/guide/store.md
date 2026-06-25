# Working with the store

The store gives a loaded corpus three things: an in-memory index that
makes records addressable by AT-URI and resolves their cross-references,
an on-disk schematic version control where a snapshot is a commit and a
named version is a tag, and derived Arrow/Parquet views for columnar
access. A content-addressed blob cache deduplicates media bytes across
corpora. This guide covers each in turn.

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

Cross-reference resolution degrades gracefully. `resolve` returns the
target model for an AT-URI, or `None` when the target is not loaded, so a
partially loaded corpus is usable and a missing target never raises. The
pool walks the full JSON dump of each record to find references, so
AT-URIs nested inside embedded objects, tuples, and union members are all
discovered:

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

didactic's Repository is a *schema* VCS, where a commit records the
structural schema, not record instances, so lairs persists each record's
value as JSON in the working tree under `records/`, indexed by AT-URI, and
registers the record type's Model schema with the VCS. `save` stages both
together, and `commit` captures the snapshot and returns the revision id:

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
revision's value set by folding the committed data read with `data_at`
over the revision's commit ancestry, keyed by AT-URI, then compares the
two sets by content. `diff` resolves both refs (so an unknown ref fails
loudly) and returns a `RecordDiff` of the `added`, `removed`, and
`changed` AT-URIs:

```python
record_diff = repo.diff("v1", "HEAD")
print(record_diff.added, record_diff.removed, record_diff.changed)
```

`schema_diff(old, new)` is the separate structural diff over two Model
*classes* (for example two generated record types across a Layers
version bump) and wraps `dx.diff`.

## Materialize Arrow views

Arrow/Parquet views are derived, rebuildable outputs, never the source of
truth: they are computed from the record store and can always be
regenerated. `materialize` reads the repository's records, groups them by
collection NSID, and writes one Parquet file per NSID into an output
directory, returning the written paths:

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
