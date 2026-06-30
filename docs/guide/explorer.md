# The explorer TUI

`lairs tui` opens a terminal user interface (TUI) for discovering, browsing, and
querying Layers data. It has four tabs: **Explore**, a browser over the discovery
index of corpora; **Discover**, a source browser for finding and indexing
datasets; **Browse**, a type-aware record explorer over a local repository that
handles every kind of Layers data; and **Query**, a workbench that runs powerful
queries over any materialized Layers data.

```bash
lairs tui --index path/to/index --repo path/to/repo --data path/to/materialized
```

All paths are optional. `--index` opens a discovery index (built with `lairs
index build`) on the Explore tab; `--repo` opens a local repository (built with
`lairs pull`) on the Browse tab; `--data` opens a directory of materialized
Parquet views on the Query tab. A tab with no source shows guidance on how to
produce one. The TUI opens on whichever tab fits the source you gave: a
repository opens on Browse, a bare materialized directory on Query, and otherwise
the Explore index.

With no `--index`, the TUI uses a default index location (under the XDG state
directory, overridable with `LAIRS_INDEX_DIR`) and, on launch, crawls the
configured sources and indexes every newly discovered dataset that you have not
muted, so the Explore tab fills in on its own. Pass `--no-auto-index` to skip
the launch crawl and index datasets by hand from the Discover tab instead.

`--repo` also feeds the Query tab: the repository is flattened into Parquet views
in a scratch directory, so `lairs tui --repo path/to/repo` gives you both a
type-aware Browse and a full Query workbench from one source. Pass `--data`
explicitly to query a different directory.

Press `1`, `2`, `3`, and `4` to switch to Explore, Browse, Query, and Discover,
`ctrl+r` to run a query, `ctrl+s` to open settings, `ctrl+t` to cycle the color
theme, `f1` for help, and `ctrl+q` to quit.

## Explore

The discovery index is an index of **corpora**: `lairs index build` crawls
repositories and records one card per `pub.layers.corpus.corpus`. The Explore
tab lists every indexed corpus, one per row. Type in the facet boxes (search
text, domain, language, license, minimum expression count) to filter and re-rank
the list live; the highlighted corpus's card, with its description, languages,
license, annotation design, ontologies, and linked eprints, renders in the
detail panel on the right.

The filtering and ranking are exactly those of `lairs index search`: the facet
boxes build a `SearchQuery`, and the same scorer orders the results.

## Discover

Where Explore reads the index you already have, **Discover finds datasets to add
to it**. It lists the configured sources on the left; pick one to crawl it (press
`enter`, or `r` to re-crawl). The crawl runs in the background and fills the table
on the right with the datasets it finds, one per row, each tagged with its state:

- `indexed`: the dataset is in your local index and shows on the Explore tab;
- `new`: discovered but not yet indexed;
- `muted`: permanently excluded from auto-indexing.

Press `enter` or `space` on a row to toggle it: a `new` (or `muted`) dataset
becomes `indexed` and appears on the Explore tab; an `indexed` dataset becomes
`muted` and is dropped from the index. Muting is permanent. A later crawl or the
launch auto-index will not re-index a muted dataset until you unmute it.

### Sources

A **source** is a PDS or relay endpoint lairs crawls for datasets. lairs ships a
built-in default for the public Layers PDS (`repo.layers.pub`), which is
deliberately kept off the firehose and so would otherwise be undiscoverable.
Sources are configured in a `sources.toml` file under the XDG config directory
(`~/.config/lairs/sources.toml`, overridable with `LAIRS_SOURCES_FILE`):

```toml
[[source]]
name = "my-pds"
endpoint = "https://pds.example"
kind = "pds"

[[source]]
name = "layers-pub"
enabled = false
```

Each `[[source]]` adds a source by `name` and `endpoint`; a `kind` of `pds` or
`relay` defaults to `pds`. An entry whose `name` matches a built-in overrides
that built-in's fields. The second entry above disables the built-in
`repo.layers.pub` without redefining it. `lairs sources list` prints the resolved
sources (add `--json` for machine-readable output), and `lairs index build
--source <name>` crawls a named source instead of a bare `--endpoint`.

### Settings

Press `ctrl+s` to open the settings modal. It lists the configured sources and
every dataset you have muted, with when and where each was muted. Highlight a
muted dataset and press `u` (or `space`) to unmute it, so a later crawl or the
launch auto-index can pick it up again. Press `esc` to close.

## Browse

Where Explore is corpus-centric, **Browse is for every kind of Layers data**. It
reads a local repository (the output of `lairs pull`) and presents its records
the way each type wants to be read. The pane has three panels:

- a **type tree** on the left, grouping the record types present in the
  repository by namespace with a count each (corpora, expressions, ontologies and
  their type definitions, resource collections and entries, experiments, judgment
  sets, agreement reports, relation graphs, annotation layers, media, personas,
  eprints, and the rest);
- a filterable **record list** in the middle, with type-appropriate columns for
  the selected type (an ontology lists name, domain, and version; an experiment
  lists measure and task; a graph edge set lists edge type and edge count);
- a **detail panel** on the right that shows the highlighted record one focused
  view at a time.

### Switching views

A record is shown through a single focused visualization, never a cluttered
dump of everything at once. Press `v` to flip between the views that fit the
highlighted record; the panel title names the current view and its position (for
example `Tree`, `3/5`), and when more than one view is available it adds a
`v: switch view` hint. A `Detail` view is always last in the cycle, so no field
is ever hidden, and a record only offers the views it actually has content for.

The views are model-driven: they dispatch on the lexicon's own type system,
selecting a view by annotation `kind`/`subkind`, judgment `taskType`, and graph
`edgeType`, and resolving each annotation's `anchor` (text byte span, token
reference, temporal span, ...) inside the chosen view. Any conforming repository
renders correctly, not just the reference corpora. The visualizations follow
established text-mode conventions:

- an **expression** (sentence) flips between **Text** (the readable sentence,
  assembled from its leaves for a document), a CoNLL-U **Grid** (one row per
  token with its tags and `HEAD`/`DEPREL` columns), a dependency **Tree**
  (indented head-to-dependent structure), brat-style **Spans** for any span
  layers over it, a **Graph** of the predicate-argument edges anchored to it, a
  **Judgments** distribution when the sentence is an experiment item, and a
  **Layers** roster of every annotation over it;
- an **annotation layer** renders by its `kind`: a token-tag layer as an
  interlinear **Tags** strip aligned under each token, a dependency layer as a
  **Tree** and a **Grid**, a span layer as brat-style underlined **Spans** over
  the text, a graph layer as resolved **Graph** edges, a tier layer as an
  ELAN-style **Timeline**, and a document-tag layer as labeled chips;
- a **judgment** distribution is drawn for the experiment's `taskType`: an
  `ordinal-scale` (Likert) response as a per-level histogram with a sparkline and
  mean/median, `magnitude` estimation on a number line with a geometric mean,
  `forced-choice` (covering 2AFC, odd-man-out, and preference), `binary`,
  `categorical`, and `multi-select` as proportion bars, and `free-text` as a
  frequency-ranked list;
- a **segmentation** renders as a token table per tokenization (index, surface,
  byte span); an **alignment** as a source-to-target **Bitext** index-link view;
- ontologies, resource collections, corpora, experiments, media, personas, and
  eprints keep their structured **Overview** (type hierarchy, entries,
  membership, experiment design, structured citation, and so on).

Type in the filter box above the record list to narrow it by any visible cell.

## Query

The Query tab runs over a directory of materialized Parquet views, and is **not
limited to corpora**. The engine registers every `*.parquet` file in the
directory as a view named after its file stem, so any materialized Layers
records are queryable through the same SQL: `Corpus.materialize` writes the
`expressions` and `annotations` views, and any other produce (ontologies,
resource collections, experiments, relation graphs, media) is queryable once its
records are materialized to Parquet alongside them.

The schema browser on the left lists every view and its columns; click a table
or column to insert its name into the editor. Choose a mode, write a query, and
press **Run** (`ctrl+r`). There are three query modes, layered from most powerful
to most ergonomic.

### SQL

Full DuckDB SQL over every materialized view. This is the general power layer:
join across record types, aggregate, use window functions, regular expressions,
and full-text search. The tables and columns available are whatever you
materialized; the schema browser shows them.

```sql
SELECT label, count(*) AS n
FROM annotations
GROUP BY label
ORDER BY n DESC
```

### Concordance

A keyword-in-context (KWIC) search. The query is a regular expression matched
against a text column (`expressions.text` by default); each hit becomes a row of
the source identifier, the left context, the matched text, and the right
context, so results read as a classic concordance.

```
\brun(s|ning)?\b
```

### CQL

A corpus query language over token-aligned annotations (the `annotations` view).
A query is a sequence of bracketed token constraints; adjacent blocks match
consecutive token positions within the same layer, so the pattern matches token
sequences. A constraint is `attribute operator "value"`, where the operator is
`=` (exact), `!=` (negated), or `~` (regular expression); an empty `[]` matches
any token.

```
[label="DET"] [label="ADJ"] [label="NOUN"]
```

```
[label~"^V" & value!="be"]
```

The attributes are the columns of the `annotations` view, which are the scalar
fields of each annotation (`label`, `value`, `text`, `confidence`, `tokenIndex`,
`headIndex`, `targetIndex`, `ontologyTypeRef`) plus `layer_uri`,
`annotation_index`, and the flattened anchor columns. Layer-level fields such as
`subkind` are not columns of this view, so they are not available as CQL
attributes; an unknown attribute is rejected. The available vocabulary of values
follows whatever the data was annotated with.

## Producing the inputs

```bash
# a discovery index of corpora for the Explore tab
lairs index build --into index --endpoint wss://relay.example

# a local repository of an account's records for the Browse tab
lairs pull <did> --endpoint https://pds.example --into repo

# materialize a corpus for the Query tab
lairs materialize <corpus-at-uri> --endpoint https://pds.example --out materialized

lairs tui --index index --repo repo --data materialized
```

The Browse tab needs only the repository, and feeds the Query tab from it too:

```bash
lairs pull <did> --endpoint https://pds.example --into repo
lairs tui --repo repo
```

The query engine is also usable on its own, without the terminal UI, over any
directory of Parquet views:

```python
from pathlib import Path
from lairs.tui import QueryEngine

engine = QueryEngine.open(Path("materialized"))
print(engine.tables)  # the views available to query
result = engine.run_sql("SELECT * FROM annotations LIMIT 20")
for row in result.rows:
    print(row.cells)
```
