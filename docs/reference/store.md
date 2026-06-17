# Store

The store holds records and their derived views: an in-memory pool with
cross-reference resolution, a schematic version-control repository, the
rebuildable Arrow views, and a content-addressed blob cache.

## Pool

An in-memory pool keyed by AT-URI, resolving cross-refs and back-refs
over the loaded record set.

::: lairs.store.pool

## Repository

A wrapper over `didactic.api.Repository` for Layers records: a corpus
snapshot is a commit and a named dataset version is a tag.

::: lairs.store.repository

## Arrow views

Derived, rebuildable columnar views with anchors flattened into typed
columns. These are never the source of truth and can be regenerated from
the record store with `materialize`.

::: lairs.store.arrow

## Blob cache

A content-addressed on-disk cache of blob bytes, keyed by CID.

::: lairs.store.blobcache
