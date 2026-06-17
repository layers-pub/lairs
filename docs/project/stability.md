# Stability

lairs is pre-1.0. This page records what callers may depend on and what
may change without a major version bump.

## Public surface

The supported API is the set of symbols documented under
[API reference](../reference/index.md). The `lairs` top-level package
re-exports the entry points most callers need: `load_corpus`, `Corpus`,
`BlobRef`, and the `codec`, `exporter`, and `knowledge_base` registry
lookups.

## Generated models

The `pub.layers.*` models under `lairs.records` are generated from the
vendored lexicons. Their shape tracks the Layers lexicons; a Layers
version bump changes them. The generation is reproducible: the vendored
lexicon tree hash is recorded in `lairs/lexicons/MANIFEST.toml` and
embedded in each generated module, and `lairs gen --check` fails when
the committed modules drift from the vendored lexicons.

## Optional integrations

Integrations (HuggingFace, PyTorch, tf.data, WebDataset, the format
codecs, the knowledge-base connectors, and the experiment-tracking
hooks) are optional extras discovered through entry points. Their
presence and their dependency pins may change between minor releases.
The four ports they bind to are the stable contract: `Codec`,
`Exporter`, `KnowledgeBase`, and `StorageBackend`.

## Deferred capabilities

Some capabilities are declared but not yet implemented, and raise
`NotImplementedError` with a description of what is missing: the
firehose consumer (`lairs.atproto.firehose`), the bulk CAR repository
pull (`lairs.atproto.pds.PdsClient.get_repo_car`), and appview-only
corpus loading without an injected client. These are tracked for later
milestones and are not part of the supported surface until implemented.
