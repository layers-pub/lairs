# Reproducibility

A corpus in lairs is reproducible: the same corpus at the same revision
yields the same records, byte for byte. That guarantee is the reason the
on-disk store is a version-control system rather than a directory of
files, and it is what lets a dataset version pin exact record content and
carry that provenance through to an export. This page explains how the
guarantee is constructed and what its limits are.

## The Repository as schema-aware version control

The on-disk source of truth is a didactic `Repository`, which is
content-addressed, versioned, and git-like, sitting over panproto's VCS.
lairs wraps it so that a corpus snapshot is a commit and a named dataset
version is a tag. This gives three properties at once: reproducibility (a
tag pins exact record content), provenance (which pull introduced or
changed a record), and cheap diffing (across Layers versions or across
re-pulls).

One fact about the upstream surface shapes the wrapper, and it is worth
stating plainly because it differs from the obvious mental model.
didactic's Repository is a *schema* VCS: staging adds a Model *class* (or
a panproto `Schema`), and a commit records the structural schema, not
record instances. lairs needs to version record *values*, so it does two
things on every save. It writes each record's value as
content-addressed JSON into the repository working tree, indexed by
AT-URI, and it stages the record type's Model schema with the underlying
VCS. A commit then captures both together: the data, in the working tree,
and its structure, in the schema history. The record set at any revision
is read back from the committed working tree, so a tag pins an exact,
byte-reproducible set of record values.

This split (schema in the VCS, values in the working tree) also
explains where lairs does work the upstream surface does not. Tag
creation is not exposed on didactic's public Repository, so the wrapper
reaches the inner panproto handle to create tags. And there is no native
revision-to-revision *data* diff on either surface, so lairs computes the
record diff itself from the stored AT-URI index: a `RecordDiff` reports
the added, removed, and changed AT-URIs between two index snapshots.
Structural diffs across two record-type schemas (for example a Layers
version bump) do go through didactic's schema diff. Both gaps are tracked
upstream as didactic issues #49 (tag creation) and #50 (revision-to-revision
data diff). The point is that the reproducibility and diffing the data
needs are constructed by lairs on top of a schema VCS, not inherited from
it.

## Content addressing

Reproducibility rests on content addressing, which lairs uses at two
levels. Record values are stored content-addressed in the working tree,
so identical values share storage and a changed value is a different
object. Blob bytes are cached content-addressed by their content
identifier (CID), under `blobs/<cid>`, shared across corpora and fetched
lazily. Because addresses are derived from content, a revision that
resolves to the same record values and the same blob CIDs *is* the same
corpus. There is no separate notion of equality to maintain. didactic's
own immutability and content-addressed hashing make this sound at the
model level: every value is frozen, so its address cannot shift under
it.

## A snapshot is a commit, a version is a tag

The version-control vocabulary maps directly onto corpus operations. A
corpus snapshot is a single commit over the working tree. A named dataset
version (`v2.1`, say) is a tag pinning that commit, and resolving the
tag later yields the exact record content committed at it. This is what
makes "load the corpus at revision `v2.1`" a precise instruction rather
than an approximate one: the tag is an immutable pointer to a
content-addressed snapshot.

It is also what makes authoring a `git`-like round trip. `pull` ingests
existing PDS records into a Repository, an author commits and tags
locally, and `publish` diffs the target revision against what is already
on the PDS and emits only the writes needed to make the PDS match. The
revision is the unit of publication, so what reaches a PDS is always a
named, diffable state.

## Arrow views are rebuildable derivations

Fast ML access is served by materialised Arrow and Parquet views: an
expressions table, an exploded annotations table, and per-record-type
tables, with anchors flattened into typed columns. These are *derived*
from the Repository and are explicitly never the source of truth.
`materialize` writes them, and they can always be regenerated from the
committed records. Treating them as a cache rather than as canonical data
is what keeps the reproducibility guarantee intact: there is exactly one
authoritative copy of the data (the Repository), and the columnar views
are a rebuildable projection of it. A consumer can delete the views and
lose nothing but the time to rebuild them.

## Provenance carried through to exports

Because a revision pins exact record content, it is also the unit of
provenance. The vendored-lexicon manifest records the source revision and
a content hash of the lexicon tree, each generated module embeds that
hash, and a corpus revision pins the record CIDs. An export carries this
bundle forward rather than copying data away from its source: an
experiment-tracking hook logs a Repository *revision* as an artifact, not
a copy, so a logged run pins exact record content, and a dataset pushed
to an external hub carries a provenance card naming the corpus AT-URI,
the Repository revision or tag, the lexicon manifest hash, and the
license from the corpus record. The external copy is a mirror, and the PDS
and the Repository stay canonical. Reproducibility therefore does not
stop at the store boundary. It travels with the data wherever an
adapter takes it.

For the operations (committing, tagging, diffing, and materialising)
see the [store guide](../guide/store.md). For how exports bind to the
revision rather than to a copy, see [integrations](integrations.md).
