# Store

The store includes an in-memory record pool with cross-reference resolution,
a schematic version-control repository, rebuildable Arrow views, and a
content-addressed blob cache.

## Pool

The in-memory pool is keyed by AT-URI and resolves cross-refs and
back-refs over the loaded record set.

::: lairs.store.pool

## Repository

The Repository wrapper adapts `didactic.api.Repository` for Layers records:
a corpus snapshot is a commit and a named dataset version is a tag.

### Store layouts

A repository's committed data is in one of two layouts, and one history may mix
them.

- **Layout 1, per record.** Written by `save` and `forget`. Each record is one
  panproto data set keyed by its AT-URI and holding exactly one record, bound to
  the record type's Model schema. A tombstone is the record
  `{"$tombstone": true}` under the forgotten AT-URI.
- **Layout 2, packed.** Written by `save_many` and `save_many_raw`. Up to
  `batch_size` records of one collection form one data set whose key is
  `lairs:pack:2:<collection NSID>:<digest>`. Its single record is an envelope
  `{"layout": 2, "collection": ..., "count": ..., "encoding":
  "jsonl+zlib+base64", "payload": ...}`, bound to the envelope's own schema. The
  payload is zlib-compressed JSON lines, one `[uri, value]` array per record, in
  staging order, with each value's JSON text exactly as written.

`content_at` and `diff` fold the data sets of each commit in staging order and a
pack's entries in payload order, oldest commit first, so the latest write of a
record wins whichever layout wrote it. A pack key or envelope whose layout
number this lairs does not know raises `panproto.VcsError` instead of being
misread.

The working tree mirrors what is staged. `index.json` maps each AT-URI to a
per-record file stem under `records/` or to `pack:<file>:<position>`, a position
in a pack file under `records/packs/`. Index updates since the last commit are
appended to `index.log` and folded into `index.json` by `commit`. `layout.json`
holds `{"layout": 2, "store": "lairs"}`; a repository without it is layout 1 and
is marked layout 2 on its first write by this lairs. `Repository.open` raises
`panproto.VcsError` for a marker naming a newer layout than
`STORE_LAYOUT_VERSION`.

::: lairs.store.repository

## Arrow views

Derived, rebuildable Arrow views flatten anchors into typed columns. They
are never the source of truth and can be regenerated from the record store
with `materialize`.

::: lairs.store.arrow

## Blob cache

The blob cache stores bytes on disk by their content-addressed CID.

::: lairs.store.blobcache
