# ATProto access

The read-only ATProto client: identity resolution, the PDS and appview
record clients, content-addressed blob fetch, and the deferred firehose
surface. The transport is `httpx`. Public reads need no auth.

## Identity

Resolves handles to DIDs, DIDs to documents, and DIDs to PDS endpoints,
caching results in memory.

::: lairs.atproto.identity

## PDS records

Wraps `com.atproto.repo.getRecord` and `listRecords`, with cursor
pagination folded into a lazy iterator and per-record decode collection.

::: lairs.atproto.pds

## Blobs

Streamed, content-addressed blob fetch over `com.atproto.sync.getBlob`.
Blob upload is owned by the authoring component and raises here.

::: lairs.atproto.blobs

## Appview

An optional thin client over the Layers appview query API, used for
discovery without walking PDSes. Responses decode through the same
envelope as the PDS.

::: lairs.atproto.appview

## Firehose

The repo firehose consumer, deferred to milestone M3. The signatures,
the `RepoSubscriber` protocol, and the `FirehoseEvent` model are real.
The streaming body raises `NotImplementedError`.

::: lairs.atproto.firehose
