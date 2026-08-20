# ATProto access

The ATProto client provides identity resolution, PDS and appview record
clients, content-addressed blob fetch, app-password session auth, and a
repo firehose consumer. The identity, PDS, blob, and appview
transports are built on `httpx`; the firehose runs over a websocket from
the `websockets` library. Public reads need no auth.

## Identity

The identity resolver maps handles to DIDs, DIDs to documents, and DIDs
to PDS endpoints, caching the results in memory.

::: lairs.atproto.identity

## PDS records

The PDS module wraps `com.atproto.repo.getRecord` and `listRecords`, folds
cursor pagination into a lazy iterator, and provides helpers that collect
decode errors per record.
`get_repo_car` and `get_repo` add the bulk path: they fetch a whole
repository as a CAR archive over `com.atproto.sync.getRepo` and decode
its Merkle search tree into record envelopes in one round trip
(`decode_repo_car` exposes the decode step on its own). `describe_repo`
returns a `RepoDescription` table of contents over
`com.atproto.repo.describeRepo` without enumerating records, and
`list_repos` enumerates hosted repository DIDs over
`com.atproto.sync.listRepos`, the seed source for a backfill crawl.

::: lairs.atproto.pds

## Blobs

The blob client fetches content-addressed data over
`com.atproto.sync.getBlob`. `get_blob` returns the blob in full, while
`iter_blob` yields it in chunks without buffering the whole blob. Blob
upload is owned by the authoring component and raises here.

::: lairs.atproto.blobs

## Appview

The optional appview client provides access to the Layers appview query API
for discovery without walking PDSes. `query` issues a raw XRPC query and
returns the decoded response body; `get` runs a `get*` method and
returns a single record envelope; `list` runs a `list*` method and
lazily iterates record envelopes across pages, with cursor pagination
folded into the iterator. Responses decode through the same envelope as
the PDS.

::: lairs.atproto.appview

## Auth

App-password sessions authorize writes and private reads. `login` resolves
an actor to its PDS and calls `com.atproto.server.createSession`;
`SessionAuth` is an `httpx.Auth` that attaches the access token and, on a
401, refreshes via `com.atproto.server.refreshSession`, falling back to a
fresh login when the refresh token has expired. `SessionStore` persists
the credential-bearing `Session` to the XDG state directory with `0600`
permissions. `authed_client` builds an HTTP client with a self-renewing
session.

::: lairs.atproto.auth

## Firehose

`subscribe_repos` consumes the repo firehose over a websocket to
`com.atproto.sync.subscribeRepos`, decodes each frame's embedded CAR
archive through the shared CAR primitives, and yields one
`FirehoseEvent` per commit op whose collection matches the Layers NSIDs.
The stream is live and unbounded: the consumer controls how many events
to take, and closing the generator closes the websocket. The
`RepoSubscriber` protocol describes the same streaming surface for an
injectable consumer.

::: lairs.atproto.firehose
