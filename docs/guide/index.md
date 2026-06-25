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
  revisions, materialize Arrow/Parquet views with flattened anchor
  columns, and cache blob bytes by content. Reach for this when a
  loaded corpus needs addressing, reproducibility, or columnar access.
- [Resolving and slicing media](media.md): resolve a media record to a
  byte handle, dispatch an annotation's anchor to the slice it points
  at, and decode and slice audio, video, and neural signals. Reach for
  this when an annotation must be turned into the waveform, frame, or
  signal window it anchors.

## Authoring and querying

- [Authoring and publishing records](authoring.md): build Layers
  records with the `lairs.author` builders, write a single record,
  publish a whole graph in one dependency-ordered `applyWrites` batch,
  inspect the dry-run plan, and pull an account's records back for a
  git-like round trip. Reach for this when producing records and writing
  them to your own PDS repository.
- [The dataset API](dataset-api.md): load a corpus, take typed
  `Dataset` views over it, walk the cross-reference graph with the join
  helpers, and read the `Features` derived from the model field specs.
  Reach for this when a loaded corpus needs a `datasets`-like access
  surface over the generated record models.

## Integrations

- [Format codecs](codecs.md): decode external annotation formats into
  Layers records and encode them back through the `Codec` port, with the
  bundled CoNLL-U and brat codecs resolved by name through the registry.
  Reach for this when moving between Layers and an existing annotation
  format.
- [Exporters](exporters.md): turn a flattened Arrow view into a
  framework-native dataset through the `Exporter` port, with the bundled
  HuggingFace `datasets`, PyTorch, tf.data, and WebDataset exporters
  resolved by name. Reach for this when feeding a corpus into a training
  pipeline.
- [Knowledge bases](knowledge-bases.md): resolve, entity-link,
  reconcile, and enrich records through the `KnowledgeBase` port, with
  the bundled Wikidata, W3C/OpenRefine reconciliation, and glazing
  connectors. Reach for this when grounding records against external
  references.
- [Experiment tracking](tracking.md): log a `Repository` revision as a
  tracked artifact with provenance for Weights & Biases and MLflow,
  pinning the exact commit and lexicon manifest hash rather than copying
  the data. Reach for this when an experiment must record which corpus
  revision it ran on.

## Tooling

- [The CLI](cli.md): drive vendoring, codegen, pulling, materializing,
  publishing, inspecting, and index operations from the `lairs`
  command-line interface. Reach for this to run lairs from a shell or a
  CI pipeline.
- [The explorer TUI](explorer.md): open a terminal interface for
  discovering corpora, browsing records by type over a local repository,
  and running queries over materialized data with `lairs tui`. Reach for
  this to explore Layers data interactively.
