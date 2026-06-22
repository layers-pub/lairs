# Architecture

lairs is a read-and-write client for the Layers format. It downloads
`pub.layers.*` records from ATProto Personal Data Servers (PDSes),
validates them against models generated from the Layers lexicons, holds
them in memory or in a content-addressed store, and exposes them through
a dataset API and an anchor-aware media layer. On the write side it
constructs records, uploads media blobs, and publishes records in bulk
to the authenticated user's own repository. The same generated models
and the same validation are used in both directions.

## The stack

The system is a pipeline of layers, each consuming the output of the one
above it. The flow is one-directional at the bottom (lexicons produce
models, full stop) and two-directional at the store (records flow in
from a PDS and out to a PDS).

```text
vendored lexicons (pub.layers.*)         single source of truth
        |
   codegen pipeline                       lairs._codegen
        |
generated dx.Model modules                lairs.records._generated
        |
   PDS  <--fetch / publish-->  records  <--decode / encode-->  dx.Model
        |                                                       instances
        v
in-memory pool + Repository (schematic VCS)        lairs.store
        |
materialized Arrow / Parquet views
        |
   Dataset API          modality tooling (audio / video / signal)
   lairs.data           lairs.media
```

Each layer is a package with a narrow responsibility:

- `lairs.lexicons` is the vendored lexicon tree plus a provenance
  manifest. It is data, not code: a verbatim copy of the Layers lexicon
  JSON and a `MANIFEST.toml` recording the source revision and a content
  hash of the tree.
- `lairs._codegen` turns those lexicons into committed Python modules.
  It parses each lexicon, maps it to a sequence of spec models, and
  emits one module per namespace. This is the load-bearing subsystem.
  The [generated-models](generated-models.md) page covers it in detail.
- `lairs.records` re-exports the generated models, namespace by
  namespace, alongside hand-written behavior over them: `BlobRef`, and
  view helpers such as `anchor_kind` and `explode_layer`. The rule is
  strict. Anything that mirrors the schema is generated. Anything that
  is behavior over the schema is ordinary code.
- `lairs.atproto` resolves identity, fetches records and blobs, and (for
  authoring) writes to a PDS.
- `lairs.store` is the on-disk and in-memory home for records: an
  AT-URI-keyed `ModelPool`, a didactic `Repository` wrapper, the Arrow
  and Parquet materialization, and a blob cache.
- `lairs.data` and `lairs.media` are the consumer-facing surfaces: the
  dataset API and the anchor resolver.
- `lairs.integrations` is the optional adapter framework, kept out of
  core and discovered at runtime.

## The two data flows

There are two ways data moves through the system, and they meet at the
store.

The **read flow** runs from a PDS into the store. `lairs.atproto`
fetches records (`getRecord` for one, paginated `listRecords` for many)
and decodes the `{uri, cid, value}` envelopes through the generated
models. A decoded record is a `dx.Model` instance. Validation failures
are collected with per-record diagnostics rather than being fatal,
because a corpus pulled from the wild may contain records that do not
validate cleanly and a single bad record should not sink the pull. The
decoded models land in the store: the `ModelPool` for immediate work, or
the `Repository` for a versioned snapshot.

The **write flow** runs from a builder out to a PDS. Records are
constructed as instances of the generated models, so authoring is
validated against the lexicons by construction. They are committed to the
local `Repository` first, where they can be tagged, diffed, and
inspected as a named revision. Publishing maps a revision to the minimal
set of PDS writes (`applyWrites`) that makes the PDS match it, ordering
the writes by cross-reference dependency so a referenced record always
exists before the record that points at it. What reaches the PDS is a
named, diffable revision rather than an untracked one-off write.

## The store as the hinge

The store is where the two flows meet, and it is deliberately the
center of gravity. Reads terminate in the store and writes originate
from it. This matters for three reasons.

First, the store decouples access from consumption. The dataset API and
the media layer read from the store, not from the network. A corpus can
be loaded once and worked with offline, materialized to columnar views,
sliced by anchor, and exported, all without touching a PDS again.

Second, the store is the reproducibility boundary. The didactic
`Repository` is the on-disk source of truth: content-addressed,
versioned, with provenance. A corpus snapshot is a commit and a named
dataset version is a tag, so the record set at a revision is
byte-reproducible. The Arrow and Parquet views are *derived* from the
Repository and are never the source of truth. They can always be
rebuilt. The [reproducibility](reproducibility.md) page develops this.

Third, the store is what makes authoring a `git`-like round trip against
a PDS. `pull` ingests existing PDS records into a Repository. An author
branches, modifies, and diffs locally, and `publish` computes the
difference against what is already on the PDS and emits only the writes
needed to close it. The local store is the authoring surface and the
version control layer at once.

## What lairs is not

lairs is not an appview. It does not maintain the canonical cross-user
index and does not consume the firehose on behalf of others. It reads
from PDSes directly (the appview query API is an optional accelerator,
never a hard dependency) and writes only to the authenticated user's own
repository, through the standard `com.atproto.repo.*` client APIs. It
never mutates another user's data.

For the mechanics of each flow, see the guides on
[reading from a PDS](../guide/reading-pds.md),
[working with the store](../guide/store.md), and
[authoring records](../guide/authoring.md). For why the models are
generated, see [generated models](generated-models.md).
