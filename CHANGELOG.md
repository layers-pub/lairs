# Changelog

All notable changes to `lairs` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **`lairs toc --counts` counts a repository in one `getRepo` pass.** Counting
  no longer drains every collection with paged `listRecords`; it fetches the
  repository CAR once and tallies Merkle-search-tree keys per collection without
  decoding record values, falling back to paged counting only when `getRepo` is
  unavailable. On a repository with hundreds of thousands of records this turns
  thousands of sequential requests into a single download (`PdsClient.count_records`
  and `count_repo_car` expose the same path). An exact count of a very large
  repository still transfers the whole repository, since ATProto exposes no
  cheaper exact count, but it is now one streamed request rather than per-page
  latency.

### Added

- **`lairs toc --max-count N`** (and `table_of_contents(count_cap=...)`) caps each
  collection's count at `N` and stops early, so a very large repository is not
  transferred in full to be counted. A collection with more than `N` records is
  reported as capped and prints as `N+`.

## [0.7.0] - 2026-09-02

### Added

- **Federated project domains.** `repo.decomp.io` (Universal Decompositional
  Semantics) and `repo.megaattitude.io` (MegaAttitude) are live PDS endpoints and
  ship as built-in discovery sources alongside `repo.layers.pub`, so all three
  project domains are browsable out of the box. `lairs sources list` shows all
  three; the index dedups by dataset URI, so crawling every source stays
  idempotent while they share a PDS.
- **Catalogue-collection datasets in the global browse.** `lairs index search`
  and the TUI Explore pane surface catalogue-collection datasets (UniMorph,
  VerbNet, WordNet, MegaAttitude), not only corpora, through a new
  `search_collections` and `CollectionHit`. Corpus-only facets (expression
  bounds, quality metric, annotation rounds) match no collection.
- **Collection datasets in the Discover tab.** The TUI Discover crawl lists
  collection-shaped datasets alongside corpora, tags each row with its type
  (`corpus` or the collection's kind), and indexes or mutes either card type;
  `DiscoveryIndex.mute` accepts a collection card, keyed by URI as before.
- **Judgment-study browsing.** `lairs.data.JudgmentStudy` and
  `load_judgment_study` load an experiment definition and its judgment sets and
  expose the study the way it is explored: its response scale, its participants,
  its items (with resolved text), the raw participant-by-item judgments, and
  per-item and per-participant distributions. `lairs judgments <uri>` prints the
  scale, each item's response distribution, and the participants. Item text
  resolves by bulk-loading the stimulus expression accounts the judgments
  reference rather than one fetch per item.
- **Judgment materialization.** `JudgmentStudy.to_arrow` and `.materialize`
  write the judgments as a long-format participant-by-item table (each row
  carrying the scalar or categorical response, confidence, and reading/response
  time) plus per-item and per-participant views, and `lairs judgments <uri>
  --out <dir>` writes
  `judgments.parquet`, `items.parquet`, and `participants.parquet`, so a study is
  queryable with DuckDB and the explorer's Query tab.
- **Judgment views in the explorer's Browse tab.** A judgment set renders its
  participant's response distribution as a per-value histogram with the mean and
  range for scalar tasks (in addition to the per-label counts for categorical
  tasks) plus the median reading/response time, and an experiment definition
  shows its scale and guidelines.
- **Signal (neural recording) view in the Browse tab.** A media record carrying
  a signal block gains a Signal view with the recording's parameters (modality,
  device, sampling frequency, duration, channel count, reference and placement
  schemes) and its channel and sensor layout. The sampled waveform lives in the
  carrier blob, which the index never stores, so the view shows the layout, not
  the samples.
- **Region reading times.** `JudgmentStudy.region_responses` flattens every
  per-region measure a judgment carries: the region's analysis role
  (`region_role`), the reading and eye-movement measures (`reading_time_ms`,
  `first_fixation_ms`, `gaze_duration_ms`, `go_past_ms`, `total_time_ms`,
  `regressions_out`, `regressions_in`, `fixation_count`), and any per-region
  response (`response_time_ms`, `scalar_value`, `categorical_value`).
  `materialize` writes them as `region_responses.parquet`, and the Browse
  judgment Distribution view summarizes them as a region count and median
  reading time. Requires Layers lexicon 0.10.0 (see below).

### Changed

- **Vendored Layers lexicon 0.10.0**, which adds an optional `regionResponses`
  array to `pub.layers.judgment.defs#judgment` so region-level reading and
  eye-tracking measurements have a home. Additive and backward compatible.
- **Documentation.** Clarified the guides, concepts, reference, and tutorials, and
  fixed the README quickstart to pass a `PdsClient` so it runs as written.

## [0.6.0] - 2026-08-20

### Added

- **Data-access surfaces.** Typed read surfaces over a repository's `pub.layers.*`
  records: `Corpus`, `Acquisition`, `Collection`, and signal-bearing `Media`, plus
  the lazy `Dataset` view, all built on a shared PDS graph loader (`lairs.data`)
  that enumerates an authority's collections and follows AT-URI references across
  account boundaries into a model pool keyed by AT-URI.
- **Single-actor collection discovery.** `lairs.discovery.collections` lists an
  actor's `pub.layers.catalog.collection` records as `CollectionSummary` rows,
  preferring a configured appview's server-side facets and falling back to a direct
  PDS read.
- **DNS handle resolution.** `IdentityResolver.resolve_handle` now races the
  `_atproto` DNS TXT record against the `.well-known/atproto-did` HTTP method and
  returns the first `did:`, so a handle served only over DNS resolves without an
  injected client. Adds a `dnspython` dependency and a `dns_timeout` setting.
- **`lairs index build` defaults to the Layers PDS.** `--endpoint` and
  `--source` are no longer a required choice: with neither flag, the crawl
  targets the first enabled configured source, which on a default install is
  the built-in Layers PDS (`repo.layers.pub`). `lairs index build --into ./index`
  is now enough to index the public corpus. A user who re-points or disables the
  built-in in `sources.toml` moves the default with it; when every source is
  disabled, the command reports that and exits non-zero rather than crawling
  nothing. The new `lairs.discovery.default_source` exposes the same resolution
  to library callers.

- **Incremental re-crawls.** `com.atproto.sync.listRepos` reports each
  repository's current commit revision, and the new
  `PdsClient.list_repo_listings` surfaces it as a `RepoListing` alongside the
  head CID (`list_repos` remains as a DID-only view). `build_index` accepts a
  `revs` mapping and skips any repository whose revision matches the one
  recorded at the last crawl, reported as `repos_unchanged` on the
  `CrawlReport` and stored as `RepoCrawlState.last_seen_rev`. `lairs index
  build` supplies the mapping whenever it enumerates the service itself, so a
  re-crawl costs one `listRepos` pass plus a `describeRepo` for only the
  repositories that actually moved. An explicit `--seed-did` list carries no
  revisions, so those repositories are always described.

### Changed

- **Dependency floors raised** to `didactic>=0.9.1` and `panproto>=0.71.0`,
  picking up upstream fixes.
- **The adapter registries are concretely parameterized.** `Registry[Codec]`,
  `Registry[Exporter]`, and `Registry[KnowledgeBase]` used the protocols bare,
  so all eight type arguments were implicitly unknown. Every codec is
  `Codec[CorpusFragment, FragmentRecord]` and every knowledge base is
  `KnowledgeBase[Entity, Candidate, Edge]`, so those are now exact; an
  exporter's view is always `pyarrow.Table` while its spec and result differ per
  adapter, so those are closed unions over the shipped adapters. A third-party
  exporter introducing a new spec or result type widens the aliases. With the
  registries typed, ty's `missing-type-argument` rule is promoted to an error,
  leaving `possibly-missing-attribute` as the one rule at its default.
- **`--source` renamed to `--source-type` on `datasets`, `toc`, and `search`.**
  On those commands the flag selects the discovery *mechanism* (`auto`, `pds`,
  or `appview`), which collided with `--source` on `lairs index build`, where it
  names a configured source. The two meanings now have two names. Because
  argparse accepts unambiguous prefixes, existing `--source pds` invocations
  keep working on the renamed commands, but scripts should move to
  `--source-type`.

### Fixed

- **The `tfdata` exporter validates before it requires tensorflow.** `export`
  imported tensorflow before reading the Arrow view, so a bad column raised
  `ModuleNotFoundError` instead of the intended lairs error whenever the
  optional extra was absent, contradicting the method's own documented
  contract. The Arrow read and its null-column check now run first.

## [0.5.0] - 2026-06-29

### Added

- **Configured dataset sources.** A `Source` model and a `sources.toml` config
  (under the XDG config directory, overridable with `LAIRS_SOURCES_FILE`) name
  the PDS and relay endpoints lairs crawls for datasets, so a PDS that is
  deliberately off the firehose stays discoverable. lairs ships a built-in
  default for the public Layers PDS (`repo.layers.pub`); a user can add sources
  or override a built-in, including disabling it. `lairs index build` accepts
  `--source <name>` as an alternative to `--endpoint`, and `lairs sources list`
  shows the configured sources.
- **Discover tab in the TUI.** A new Discover tab (`4`) browses the configured
  sources and crawls a chosen source in the background, listing each dataset with
  its state (`indexed`, `new`, or `muted`). Pressing `enter` or `space` on a row
  indexes a new dataset (so it appears on Explore) or permanently mutes an
  indexed one. The crawl reuses the same `listRepos` path as `lairs index build`
  through a new streaming `discover` function in `lairs.discovery`.
- **Auto-index on launch.** With no `--index`, the TUI uses a default index
  location (under the XDG state directory, overridable with `LAIRS_INDEX_DIR`)
  and, on launch, crawls the enabled sources and indexes every newly discovered
  dataset that is not muted, so Explore fills in on its own. `lairs tui
  --no-auto-index` skips the launch crawl.
- **Permanent muting with review.** A muted dataset is recorded as a
  `MutedDataset` in the index and excluded from auto-indexing until unmuted. A
  settings modal (`ctrl+s`) lists the configured sources and every muted dataset,
  with an unmute action so a later crawl can pick it up again.

## [0.4.1] - 2026-06-29

### Fixed

- **Querying a materialized dataset with no annotations.** A dataset without
  annotation layers materialized an `annotations.parquet` with no columns, which
  DuckDB cannot read, so the Query tab and `QueryEngine` failed to open the
  dataset (and `tui --data` crashed). `materialize` now skips a column-less view
  rather than writing an unreadable Parquet, and `QueryEngine.open` skips any
  Parquet it cannot register (raising only when none are readable), so querying
  an annotation-less dataset works.

## [0.4.0] - 2026-06-29

### Added

- **Cross-account materialization.** `load_corpus` (and the `lairs materialize`
  and `lairs inspect` commands built on it) now follow AT-URI references across
  account boundaries, transitively, to pull in the component records a dataset is
  built from (its expressions, and the records those reference in turn), since a
  Layers dataset typically fans out across many single-purpose accounts rather
  than living in one. A new `follow_refs` parameter, exposed on the CLI as
  `--follow-refs` / `--no-follow-refs` (enabled by default), controls this, for
  example to read only the corpus's own account when the components are already
  materialized. References are fetched by exact AT-URI, so only the records the
  corpus actually cites are loaded.

### Fixed

- **Reading records back from a PDS.** `lairs pull` and `load_corpus` (and the
  `materialize` and `inspect` commands) validated each record with the wire
  `$type` field that the generated models do not declare, so every real PDS
  record failed validation and was silently skipped (`pull` reported zero
  records; `materialize` wrote empty views). They now strip `$type` before
  validation through the shared `decode` helper, so records read back correctly.

## [0.3.0] - 2026-06-26

### Added

- **Aggregate per-dataset changelog entries.** `build_aggregate_entry` assembles
  a single `pub.layers.changelog.entry` for a dataset anchor from the diffs of the
  many component records that make up that dataset (a new `ComponentChange` value
  type), grouping changes into `ChangeSection`s by each component's category and
  pointing `ChangeItem.targets` at the changed components. The version is bumped
  once from the whole aggregate, monotonic from the supplied previous version, and
  an aggregate with no real change does not bump. A scale guard keeps each item's
  true count in its `description` and caps the enumerated `targets` at
  `targets_per_item`, so a change touching many records is summarised, never
  silently truncated.

## [0.2.0] - 2026-06-25

### Added

- **Auto-generated changelogs.** `generate_changelog` and `build_entry` derive a
  `pub.layers.changelog.entry` and its `SemanticVersion` from the field-level diff
  of a record between two revisions, behind a pluggable bump classifier (patch for
  value edits, minor for additions, major for removals or identity breaks). The
  field walk records a `fieldPath`, previous value, and new value per change, and
  groups change items into sections by the subject's category.
- **Publish changelog hook.** `publish(..., changelog=True)` augments the write
  plan with a changelog entry per changed record alongside the data writes,
  reading the prior version from the most recently published entry on the PDS so
  versions stay monotonic across runs. The default `changelog=False` leaves the
  plan unchanged.
- **`Repository.content_at`.** Returns the decoded record values present at a
  revision, keyed by AT-URI, folding the commit ancestry and its tombstones.

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

[Unreleased]: https://github.com/layers-pub/lairs/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/layers-pub/lairs/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/layers-pub/lairs/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/layers-pub/lairs/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/layers-pub/lairs/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/layers-pub/lairs/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/layers-pub/lairs/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/layers-pub/lairs/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/layers-pub/lairs/releases/tag/v0.1.0
