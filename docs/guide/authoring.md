# Authoring and publishing records

This guide covers building Layers records with the `lairs.author` builders,
writing a single record, publishing a whole graph in one dependency-ordered
batch, inspecting the dry-run plan, and pulling an account's records back for a
git-like round trip.

Writes target only the authenticated user's own repository. The write client
never accepts another repository's DID at a write call, and OAuth is not handled
here: an authenticated `httpx.Client` carrying the session's bearer token and
write scopes is injected. See [Concepts](../concepts/) for why the write path is
isolated in the authoring component.

For signatures, see the [reference](../reference/). This guide shows the task
path and the load-bearing options.

## Building anchors

An annotation attaches to source data through an
[`Anchor`](../reference/). The builders in `lairs.author` construct the correct
anchor sub-model and validate every argument against the lexicon constraints at
construction time, raising `BuildError` rather than deferring to a PDS rejection.

```python
from lairs.author import span, token_ref, temporal, bbox, keyframe, spatio_temporal
from lairs.records._generated.defs import TemporalSpan

text = span(0, 11)                       # byte offsets, byte_end >= byte_start
tok = token_ref("tokenization-0", 3)     # tokenisation UUID, 0-based index
clip = temporal(1000, 4000)              # milliseconds, end_ms >= start_ms

box = bbox(x=10, y=20, width=64, height=48)   # width/height at least one pixel
frame = keyframe(time_ms=1000, box=box)
track = spatio_temporal(
    TemporalSpan(start=1000, ending=4000),
    keyframes=(frame,),
    interpolation="linear",              # open vocabulary, "linear" by default
)
```

`span`, `token_ref`, `temporal`, and `spatio_temporal` return an `Anchor`. `bbox`
and `keyframe` return their own value models, used inside a keyframe or wherever
a model embeds a bounding box. A `BuildError` is raised when an offset is
negative, a span is not well ordered, no keyframes are supplied, or a width or
height falls below the lexicon minimum.

## Building an annotation layer

`LayerBuilder` collects annotations, minting a UUID for any that lack one, and
finalises them into a single `AnnotationLayer`. The layer `kind`, `subkind`, and
`formalism` are validated against the model's open vocabulary: an unknown but
non-empty community value is accepted, an empty string is rejected.

```python
from datetime import UTC, datetime
from lairs.author import LayerBuilder, span

builder = LayerBuilder(
    expression="at://did:plc:author/pub.layers.expression.expression/abc",
    kind="span",
    created_at=datetime.now(UTC),
    subkind="ner",
    formalism="conll-2003",
)
builder.add(anchor=span(0, 5), label="PER", confidence=950)
builder.add(anchor=span(9, 20), label="ORG")
layer = builder.build()                   # raises BuildError if no annotations
```

`confidence` is validated against the model's 0-1000 range, and `token_index`
against its minimum. `build` raises `BuildError` when no annotations were added.

## Cross-references before publication

A record frequently references another record (an expression, a media record, an
ontology) before that target has an AT-URI, because the whole graph is published
as one batch. Use `PendingId` for an unpublished target and `reference` to
resolve a target to a reference string whatever its publication state:

```python
from lairs.author import PendingId, reference

pending = PendingId("expr-1")             # a stable local id within a session
ref = reference(pending)                  # -> "expr-1"
ref = reference(published_expression)     # reads the model's uri field
ref = reference("at://did:plc:x/c/rkey")  # an AT-URI string passes through
```

`reference` raises `BuildError` when a model target carries no resolvable AT-URI.
Pass a `PendingId` in that case. The publish path resolves each `PendingId` to a
real AT-URI once the referenced record commits.

## A single write

`WriteClient` wraps `uploadBlob`, `createRecord`, `putRecord`, `deleteRecord`,
and `applyWrites`. Construct it with the PDS endpoint, the authenticated
repository DID, and the injected authenticated client. Every write passes the
owning DID, so the safety scope is explicit at the call site.

```python
from lairs.author import WriteClient

with WriteClient("https://pds.example", "did:plc:author", client=session) as wc:
    blob = wc.upload_blob(audio_bytes, "audio/wav")     # honours the 100MB cap
    result = wc.create_record(
        "pub.layers.expression.expression",
        value=expression.model_dump(),
        rkey=None,                                       # PDS assigns a TID
    )
    print(result.status, result.uri, result.cid)        # "created", ...
```

`create_record`, `put_record`, and `delete_record` each return one `WriteResult`
with a status of `created`, `updated`, or `deleted`. A batch failure that is
retried reports `failed` with a reason. Blob uploads are content-addressed within
a session, so the same bytes uploaded twice reuse the first blob reference. A
transport or non-success response raises `WriteError`.

## Bulk publishing with `applyWrites`

`WriteClient.apply_writes` (and the module-level `apply_writes`) take a sequence
of `WriteOp` and apply them in dependency order, chunked, with idempotent retry:

- **Dependency ordering.** `order_writes` sorts creates and updates by the
  collection's dependency tier (media, ontologies, and personas first, then
  expressions, then segmentations, then annotations, graphs, and corpora, then
  records that reference those), so a referenced record always commits before its
  referrer.
- **Chunking.** Writes are sent in batches of at most `APPLY_WRITES_CHUNK` (200).
- **Idempotent retry.** When a batch call fails, the chunk is retried one write
  at a time as `putRecord` upserts on deterministic rkeys, so a partially applied
  batch is resumed rather than duplicated.
- **Per-record results.** Each input `WriteOp` yields exactly one `WriteResult`.
  Per-record failures are captured, not raised.

`deterministic_rkey` derives a stable rkey from a record value (the first 24 hex
characters of the SHA-256 of its canonical JSON), so re-publishing the same
content upserts the same record.

## Publishing a Repository revision

`lairs.author.publish.publish` maps a local Repository revision to the minimal
`applyWrites` plan by diffing the revision against what is already on the PDS, by
AT-URI and content identity. Reach it through the module path. The package does
not re-export `publish` as a top-level name (a same-named symbol would shadow the
submodule).

```python
from lairs.author.publish import publish
from lairs.store.repository import Repository

repo = Repository.open("/path/to/repo")

# dry run: compute and return the plan without sending any writes.
plan = publish(repo, "HEAD", to="did:plc:author", endpoint="https://pds.example",
               dry_run=True)
print(plan.creates, plan.updates, plan.deletes)
print(plan.is_empty())

# live publish: applies the plan's writes in dependency order, returns the plan.
publish(repo, "v1", to="did:plc:author", endpoint="https://pds.example",
        client=session)
```

The returned `PublishPlan` carries the target `repo`, the `revision`, and the
`creates`/`updates`/`deletes` as ordered `WriteOp` tuples. `creates` are records
in the revision but not on the PDS. `updates` are records present in both whose
content identity differs. `deletes` are records on the PDS but absent from the
revision. `PublishPlan.ordered_writes` returns the full set in safe application
order: deletes first in reverse dependency order (referrers before targets), then
creates and updates in forward dependency order. A live publish requires an
endpoint, and calling it without one raises `WriteError`.

## Pulling for a git-like round trip

`pull` ingests an account's Layers records into a Repository. Each collection is
enumerated over the PDS read client, every value is decoded against its generated
model and staged under its AT-URI, and a record that fails to validate is skipped
rather than aborting the pull.

```python
from lairs.author.publish import pull
from lairs.store.repository import Repository

repo = Repository.init("/path/to/repo")
pull("did:plc:author", endpoint="https://pds.example", into=repo)
revision = repo.commit("pull layers records")
```

This gives the git-like cycle: pull, branch, modify, diff, and `publish` back.
The same flow is available from the command line. See the [CLI guide](cli.md).

## See also

- [Dataset API](dataset-api.md) for reading and joining the records you author.
- [Tracking](tracking.md) for logging a published revision with provenance.
- [CLI](cli.md) for `pull`, `publish`, and the dry-run-by-default safety.
