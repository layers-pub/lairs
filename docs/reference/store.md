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

::: lairs.store.repository

## Arrow views

Derived, rebuildable Arrow views flatten anchors into typed columns. They
are never the source of truth and can be regenerated from the record store
with `materialize`.

::: lairs.store.arrow

## Blob cache

The blob cache stores bytes on disk by their content-addressed CID.

::: lairs.store.blobcache
