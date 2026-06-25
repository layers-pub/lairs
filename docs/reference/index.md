# API reference

Per-symbol documentation generated from the source docstrings. Use this
when you know what you want to call and need the exact signature,
parameter list, raised exceptions, and return type. For task-oriented
walk-throughs see the [guides](../guide/index.md). For design rationale
see the [concepts](../concepts/index.md).

## Records and data

- [Records](records.md): `BlobRef`, the view helpers, and the generated
  `pub.layers.*` record namespaces.
- [Shared types](types.md): the `JsonValue` alias and the type variables.
- [Dataset API](data.md): `Corpus` and `load_corpus`, the lazy `Dataset`,
  and the `Features` description derived from the generated models.
- [Dataset discovery](discovery.md): `discover_datasets`,
  `list_datasets`, and `table_of_contents`, the `DatasetFilter`,
  `DatasetSummary`, and `RepoTableOfContents` result shapes, and the
  searchable discovery index.

## ATProto access

- [ATProto access](atproto.md): identity resolution, the PDS and appview
  record clients, blob fetch, and the firehose surface.

## Store

- [Store](store.md): the in-memory pool, the schematic Repository, the
  Arrow views, and the blob cache.

## Media

- [Media](media.md): media resolution, anchor resolution, and the audio,
  video, and neural decode and slicing helpers.

## Authoring

- [Authoring](author.md): the `LayerBuilder` and anchor builders (`span`,
  `temporal`, `bbox`, and the rest), the `WriteClient`, `apply_writes`,
  `pull`, and the `PublishPlan` diff against a PDS.

## Integrations

- [Integration ports](ports.md): the `Codec`, `Exporter`,
  `KnowledgeBase`, and `StorageBackend` protocols that adapters bind to.
- [Adapter registry](registry.md): the registry and the top-level
  `get_codec`, `get_exporter`, and `get_knowledge_base` lookups by name.
- [Format codecs](codecs.md): the shared corpus-fragment models and the
  CoNLL-U and brat codecs.
- [Knowledge bases](kb.md): the entity, candidate, and edge models and
  the Wikidata, reconciliation, and glazing connectors.
- [Exporters](exporters.md): the framework-native exporters over an Arrow
  view (HuggingFace, PyTorch, TensorFlow, WebDataset).
- [Experiment tracking](tracking.md): logging a Repository revision and
  its provenance bundle to Weights & Biases or MLflow.

## Code generation

- [Code generation](codegen.md): the lexicon-to-model pipeline, the
  schema-to-spec mapping, the emitter, and the vendoring manifest.

## Tools

- [Explorer TUI](explorer.md): the `lairs.tui` Textual application and
  the standalone DuckDB-backed `QueryEngine`.
- [CLI](cli.md): the `lairs` console script and its `vendor`, `gen`,
  `pull`, `materialize`, `publish`, `inspect`, `datasets`, `toc`,
  `search`, `index` (with `build`, `update`, `search`, and `diff`),
  `tui`, `login`, `logout`, and `whoami` subcommands.
