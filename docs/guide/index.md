# Guides

The guides are task-oriented. Each one assumes a reader who knows what
result they want and answers a question of the form "how do I do X"
against one subsystem. They are not exhaustive: each names the options
that matter for the task and links to the [reference](../reference/index.md)
for full signatures and to the [concepts](../concepts/index.md) for the
rationale.

Read the [tutorial](../tutorial/index.md) first if lairs is unfamiliar.
It works the same ground on a single running example.

## Reading and ingesting

- [Generating record models](codegen.md): vendor a Layers lexicon
  tree, regenerate the committed `pub.layers.*` models, and run the
  drift gate. Reach for this when updating to a new Layers version. The
  models are generated and committed, never hand-written.
- [Reading from a PDS](reading-pds.md): resolve a handle to a DID to a
  PDS endpoint, fetch records with `getRecord` and paginated
  `listRecords`, decode the envelopes into generated models, and fetch
  blobs. Reach for this to pull records off any PDS without authoring or
  authenticating.

## Storing and slicing

- [Working with the store](store.md): hold records in the in-memory
  `ModelPool` with AT-URI resolution and back-references, persist a
  corpus snapshot as a commit in the `Repository`, tag and diff
  revisions, materialise Arrow/Parquet views with flattened anchor
  columns, and cache blob bytes by content. Reach for this when a
  loaded corpus needs addressing, reproducibility, or columnar access.
- [Resolving and slicing media](media.md): resolve a media record to a
  byte handle, dispatch an annotation's anchor to the slice it points
  at, and decode and slice audio, video, and neural signals. Reach for
  this when an annotation must be turned into the waveform, frame, or
  signal window it anchors.
