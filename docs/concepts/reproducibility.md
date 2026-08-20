# Reproducibility

A corpus in lairs is reproducible: the same corpus at the same revision
yields the same records, byte for byte. The on-disk store is thus a
version-control system rather than a directory of files. A dataset
version pins exact record content and carries that provenance through to
an export.

## The Repository as schema-aware version control

The on-disk source of truth is a content-addressed, versioned didactic
`Repository` built on panproto's VCS. lairs represents a corpus snapshot
as a commit and a named dataset version as a tag. A tag pins exact record
content, commit history records which pull introduced or changed a
record, and content addressing supports cheap diffs across Layers
versions or re-pulls.

didactic's Repository is a schema VCS first, which shapes the lairs
wrapper. `add` stages a Model class (or a panproto `Schema`) and records
the structural schema. It also versions record values. `add_data` stages
a record's value as committed data, keyed by AT-URI and associated with
that schema. lairs uses both on every save. It writes each record's value
as JSON under `records/`, stages that value as committed data under its
AT-URI, and stages the record type's Model schema alongside it. A commit
captures both: the values, as committed data, and their structure, in the
schema history. The values
committed at a revision are read back through `data_at` under their AT-URI
keys, so a tag pins an exact, byte-reproducible set of record values.

didactic 0.9.0 exposes tag creation, the committed-data write, and the
committed-data read on the public Repository surface, all of which the
wrapper uses directly. A revision-to-revision diff reconstructs the value
set at each revision by folding `data_at` over the revision's commit
ancestry, keyed by AT-URI, then compares the two sets by content.
Structural diffs across two record-type schemas (a Layers version bump,
say) go through didactic's schema diff. The reproducibility the data needs
is backed by committed data, read back at any revision, rather than
reconstructed from loose files.

## Content addressing

Reproducibility rests on content addressing, which lairs uses at two
levels. Record values are stored content-addressed in the working tree,
so identical values share storage and a changed value is a different
object. Blob bytes are cached content-addressed by their content
identifier (CID), under `blobs/<cid>`, shared across corpora and fetched
lazily. Because addresses are derived from content, a revision that
resolves to the same record values and the same blob CIDs *is* the same
corpus. There is no separate notion of equality to maintain. didactic
supports this guarantee at the model level through immutable values and
content-addressed hashes: a frozen value's address cannot shift under it.

## A snapshot is a commit, a version is a tag

The version-control vocabulary maps directly onto corpus operations. A
corpus snapshot is a single commit over the working tree, and a named
dataset version (`v2.1`, say) is a tag pinning that commit. Resolving the
tag later yields the exact record content committed at it. Thus, "load
the corpus at revision `v2.1`" identifies an immutable pointer to a
content-addressed snapshot.

The same mapping supports a `git`-like authoring round trip. `pull` ingests
existing PDS records into a Repository, an author commits and tags
locally, and `publish` diffs the target revision against what is already
on the PDS and emits only the writes needed to make the PDS match. The
revision is the unit of publication, so what reaches a PDS is always a
named, diffable state.

## In-record reproducibility metadata

The store guarantee above is about record *values*: the same revision
yields the same bytes. A record may also carry reproducibility metadata
*in its value*, describing how the artifact it represents was produced.
That metadata is the `ReproducibilityInfo` def (code URI, commit hash,
command, environment, random seed). It is a shared def, carried by the
produce records that release a computational artifact (the corpus, the
annotation layer, the segmentation, the cluster set, the alignment, the
edge set, the experiment definition) as well as by the eprint data link,
rather than living only on eprints. The two are complementary: the store
pins what the records contain, and `ReproducibilityInfo` records how a
producer would regenerate the artifact those records describe.

## Arrow views are rebuildable derivations

Fast ML access is served by materialized Arrow and Parquet views: an
expressions table, an exploded annotations table, and per-record-type
tables, with anchors flattened into typed columns. These are *derived*
from the Repository and are explicitly never the source of truth.
`materialize` writes them, and they can always be regenerated from the
committed records. Treating them as a cache preserves one authoritative
copy of the data in the Repository; the columnar views remain rebuildable
projections. A consumer can delete the views and lose nothing but the time
to rebuild them.

## Provenance carried through to exports

Because a revision pins exact record content, it is also the unit of
provenance. The vendored-lexicon manifest records the source revision and
a content hash of the lexicon tree, each generated module embeds that
hash, and a corpus revision pins the record CIDs. An experiment-tracking
hook logs a Repository *revision* as an artifact, not a copy, so a logged
run pins exact record content. A dataset pushed to an external hub carries
a provenance card naming the corpus AT-URI, the Repository revision and
tag, the lexicon manifest hash, the Layers version, and a license
identifier supplied by the caller from the corpus record. The card stores
that license string verbatim. The structured `licensing` to SPDX
projection, expression else the first license's slug, belongs to the
discovery summary, not the export card. The external copy is a mirror,
while the PDS and the Repository stay canonical.
The tracking hook and Hub helpers retain this provenance beyond the store
boundary.

For the operations (committing, tagging, diffing, and materializing)
see the [store guide](../guide/store.md). For how exports bind to the
revision rather than to a copy, see [integrations](integrations.md).
