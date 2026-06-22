# Reading from a PDS

lairs reads `pub.layers.*` records directly from a Personal Data Server
over the XRPC HTTP interface. Public reads need no authentication, and an
injected HTTP client can carry a session for private reads. This guide
covers the read path end to end: resolve an identity, fetch records,
decode the envelopes into generated models, and fetch blobs. The
optional appview client is a discovery accelerator over the same
envelope shape.

The transport throughout is `httpx`, not the `atproto` SDK. For full
signatures see the [ATProto reference](../reference/atproto.md). For why
direct PDS access is the contract rather than the appview, see
[Architecture](../concepts/architecture.md).

## Resolve an identity

A read starts from a handle or a DID and ends at a PDS endpoint.
`IdentityResolver` resolves a handle to a DID (via the
`.well-known/atproto-did` HTTP endpoint), a DID to its DID document (via
the PLC directory for `did:plc`, or the `did:web` document URL), and a
DID to its PDS service endpoint. Results are cached in memory for the
life of the resolver, so repeated lookups during a pull do not re-hit the
network.

```python
from lairs.atproto.identity import IdentityResolver

with IdentityResolver() as resolver:
    resolution = resolver.resolve("alice.bsky.social")

print(resolution.did)           # did:plc:...
print(resolution.pds_endpoint)  # https://pds.example
print(resolution.handle)        # alice.bsky.social
```

`resolve` accepts either a handle or a DID: a DID short-circuits handle
resolution and returns with `handle` set to `None`. The individual steps
are also available as `resolve_handle`, `resolve_did`, and `resolve_pds`,
each with a module-level throwaway-resolver wrapper for one-shot use. A
failure at any step raises `IdentityError`, which wraps DNS, HTTP, and
document-shape failures behind one type.

Handle resolution uses only the HTTP `.well-known` path. The DNS
`_atproto` TXT method is not in core, since it would add a DNS resolver
dependency. Inject a client that performs the TXT lookup if a handle is
served only over DNS.

## Fetch records

`PdsClient` wraps `com.atproto.repo.getRecord` and
`com.atproto.repo.listRecords`. Construct it with the PDS endpoint and
use it as a context manager so the private HTTP client is closed:

```python
from lairs.atproto.pds import PdsClient

with PdsClient(resolution.pds_endpoint) as client:
    one = client.get_record(
        resolution.did,
        "pub.layers.expression.expression",
        "3k...",
    )
    print(one.uri, one.cid)
```

`listRecords` is paginated. `PdsClient.list_records` folds the cursor
into a lazy iterator: each page is requested only when the consumer
advances past the previous one, and iteration stops when the PDS stops
returning a cursor. The default page size is 100. Override it with
`limit`, and resume from a saved `cursor`:

```python
with PdsClient(resolution.pds_endpoint) as client:
    for envelope in client.list_records(
        resolution.did,
        "pub.layers.expression.expression",
        limit=50,
    ):
        ...  # streamed across all pages
```

The module-level `get_record` and `list_records` use a throwaway client.
The module-level `list_records` drains every page into a list and closes
the client, so prefer `PdsClient.list_records` over an open client for
true streaming.

The bulk `com.atproto.sync.getRepo` CAR path (`PdsClient.get_repo_car`)
is deferred: it raises `NotImplementedError` because CAR / DAG-CBOR
block decoding is out of scope for the read milestone.

## Decode envelopes into models

Each response is the standard ATProto record envelope, modeled as
`RecordEnvelope` with `uri`, `cid`, and a `value` that holds the record's
JSON. `decode` validates one envelope's value against any `dx.Model`
target and returns the typed instance:

```python
from lairs.atproto.pds import decode
from lairs.records._generated.expression import Expression

expression = decode(one, Expression)
print(expression.text)
```

`decode` raises `dx.ValidationError` if the value does not validate (or is
not a JSON object). For a batch, `decode_all` decodes every envelope and
collects per-record failures instead of failing fast: it returns a
`(records, failures)` pair, where `failures` is a tuple of
`RecordDecodeFailure` models carrying the offending `uri`, `cid`, and a
human-readable `error`. One malformed record never aborts the batch.

```python
from lairs.atproto.pds import decode_all

with PdsClient(resolution.pds_endpoint) as client:
    envelopes = list(
        client.list_records(
            resolution.did,
            "pub.layers.expression.expression",
        )
    )

records, failures = decode_all(envelopes, Expression)
print(len(records), "decoded,", len(failures), "failed")
for failure in failures:
    print(failure.uri, failure.error)
```

## Fetch blobs

`BlobClient` wraps `com.atproto.sync.getBlob` for content-addressed media
bytes. `get_blob` streams the response in chunks and returns a
`BlobBytes` holder carrying the `did`, `cid`, the raw `data` (in an
opaque field), and the `mime_type` reported by the PDS:

```python
from lairs.atproto.blobs import BlobClient

with BlobClient(resolution.pds_endpoint) as client:
    blob = client.get_blob(resolution.did, "bafkrei...")
    print(blob.mime_type, len(blob.data))
```

`iter_blob` yields the chunks without buffering the whole blob, for
streaming a large media file straight to disk. This module does not
cache. Caching by CID is owned by the [store](store.md) and
[media](media.md) layers. Blob upload (`com.atproto.repo.uploadBlob`) is
a write and lives in the authoring component. The `upload_blob` here is a
deferred stub that raises `NotImplementedError`.

## Query the appview (optional)

The appview is an accelerator for discovery and cross-ref resolution
without walking PDSes. lairs works with it off, where direct PDS access
is the contract. `AppviewClient` is a thin client over the Layers query
methods (`pub.layers.*.get*` and `list*`). A bare NSID such as
`corpus.listCorpora` is prefixed with `pub.layers.`. Responses use the
same `{uri, cid, value}` envelope, so they decode through the same
generated models:

```python
from lairs.atproto.appview import AppviewClient

with AppviewClient("https://appview.example") as appview:
    corpus = appview.get("corpus.getCorpus", {"uri": "at://..."})
    for envelope in appview.list("corpus.listCorpora", {}):
        ...  # cursor pagination folded into the iterator
```

`get` returns a single `RecordEnvelope`, and `list` lazily iterates
envelopes across pages, reading the records array from `results_key`
(default `records`) and following the cursor. `query` returns the raw
decoded response body when neither shape fits.

## See also

- [ATProto reference](../reference/atproto.md) for full client and
  function signatures.
- [Working with the store](store.md) for holding and addressing the
  records once fetched.
- [Architecture](../concepts/architecture.md) for the read-only
  contract and the PDS-versus-appview distinction.
