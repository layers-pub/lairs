# Changelog

All notable changes to `lairs` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-25

The first public release. `lairs` is a read/write dataset client for the
[Layers](https://github.com/layers-pub) format on the AT Protocol: the mental
model is `datasets` and `git` for decentralised linguistic annotation. It is
built on [didactic](https://github.com/panproto/didactic) and
[panproto](https://github.com/panproto/phrom); every structured value is a
didactic model.

### Added

- **Generated record models.** Typed models for the 26 `pub.layers.*` record
  types, generated from the vendored Layers lexicons, with a content-addressed
  `BlobRef` value type and a drift gate (`lairs gen --check`).
- **ATProto access layer.** Read records and whole repositories from a Personal
  Data Server over XRPC, decode CAR/DAG-CBOR commits, resolve handles and DIDs,
  and follow the firehose with cursor-based reconnect.
- **Schema-aware local store.** A panproto-backed, git-like repository where a
  corpus snapshot is a commit and a dataset version is a tag, with collision-free
  record files, a deletion/tombstone path, and revision-to-revision diffs. An
  Arrow/Parquet materialiser flattens records and polymorphic anchors into typed
  columns.
- **Dataset and corpus API.** A HuggingFace-`datasets`-like surface with lazy and
  streaming `Dataset`, feature derivation, and a `Corpus` scoped to its
  membership records with train/dev/test split accessors.
- **Authoring and publishing.** Validated-by-construction builders, blob upload,
  and dependency-ordered bulk publishing to the authenticated user's own
  repository, with an idempotent re-publish that is a no-op for unchanged
  records (including blob-bearing media, expression, and persona records).
- **Media layer.** On-demand resolution of audio, video, and time-series signals
  behind injected fetcher and content-addressed cache ports, with anchor
  resolution over the full anchor union (text, token, temporal, spatio-temporal,
  page, and external targets).
- **Dataset discovery.** Crawl the Layers network for corpora, maintain a local
  searchable index with a DuckDB query accelerator, tail the firehose to keep the
  index fresh (including deletions), and diff index revisions.
- **Format codecs.** brat stand-off and CoNLL-U import/export, discoverable
  through entry points.
- **Framework exporters.** HuggingFace `datasets` and Hub push/pull, PyTorch
  (map-style and worker-sharded iterable), `tf.data`, and WebDataset exporters,
  each behind an optional extra.
- **Knowledge-base connectors.** Wikidata, OpenRefine reconciliation, and Glazing
  connectors behind a common port, with experiment-tracking provenance for
  MLflow and Weights & Biases.
- **Terminal explorer.** `lairs tui`, a colourful three-tab TUI to Explore the
  discovery index, Browse every record type in a repository with model-driven,
  view-switched visualisations (CoNLL-U grids, dependency trees, span overlays,
  judgment distributions, alignments, and more), and Query materialised data with
  SQL, a KWIC concordance, and a CQL token-pattern language.
- **Command-line interface.** The `lairs` command for vendoring lexicons,
  regenerating models, pulling and materialising corpora, publishing, inspecting
  repositories, discovering datasets, building and searching the index, managing
  sessions, and launching the explorer.

[Unreleased]: https://github.com/layers-pub/lairs/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/layers-pub/lairs/releases/tag/v0.1.0
