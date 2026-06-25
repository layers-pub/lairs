# The `lairs` command-line interface

This guide covers the `lairs` command and its subcommands. The CLI is built on
the standard-library `argparse`, so it adds no command-line dependency. Each
subcommand dispatches to a finished component call.

The subcommands fall into four families:

- maintenance: `vendor`, `gen` (and `gen --check`)
- corpora: `pull`, `materialize`, `publish`, `inspect`
- discovery: `datasets`, `toc`, `search`, `index` (with `build`, `update`,
  `search`, `diff`)
- authentication: `login`, `logout`, `whoami`

There is also `tui`, which launches the interactive explorer.

Run `lairs` with no subcommand to print help; the process then exits with code
`2`. Each subcommand has its own `--help`.

```bash
lairs --help
lairs publish --help
```

## `vendor`

Refresh the vendored `pub/layers` lexicon tree from a local Layers checkout and
rewrite `MANIFEST.toml` provenance.

```bash
lairs vendor --from /path/to/layers/lexicons/pub/layers \
  --layers-version 1.2.0 --layers-git-sha abc123 --vendored-at 2026-06-16
```

`--from` is required and points at a `lexicons/pub/layers` tree. The three
provenance flags are optional and keep the existing values when omitted. When the
copied tree is byte-identical to the one already vendored, the existing hash and
vendoring date are kept, so a no-op re-vendor does not invalidate the committed
generated models. A missing source tree exits non-zero. Fetching by a git ref is
a thin wrapper over this step: check out the ref first, then point `--from` at its
tree.

## `gen` and `gen --check`

Regenerate the committed record models from the vendored lexicons.

```bash
lairs gen                                # write the modules
lairs gen --check                        # the CI drift gate
```

`gen` writes the generated modules and reports how many. `gen --check` compares
the committed modules against a fresh generation and exits non-zero when they are
stale, without writing. This is the drift gate. Records are generated, never
hand-authored: edit the generator, not the output.

## `pull`

Ingest an account's Layers records from a PDS into a local Repository for a
git-like round trip.

```bash
lairs pull did:plc:author --endpoint https://pds.example --into ./repo \
  --message "pull layers records"
```

The DID is positional, and `--endpoint` and `--into` are required. Every Layers
collection of the account is read and staged into the Repository under its
AT-URI. The snapshot is then committed and the commit reported. When nothing is
pulled, no commit is made.

## `materialize`

Load a corpus from a PDS and write its normalized Arrow/Parquet views.

```bash
lairs materialize at://did:plc:author/pub.layers.corpus.corpus/abc \
  --endpoint https://pds.example --out ./views
```

The corpus AT-URI is positional, and `--endpoint` and `--out` are required. The
`expressions` and `annotations` views are written into the output directory and
listed.

## `publish`

Diff a local Repository revision against a PDS and emit the minimal `applyWrites`
plan. **Publishing is a dry run by default.** The plan is printed and nothing is
written unless `--yes` is passed.

```bash
# dry run (default): show the plan, write nothing
lairs publish --repo ./repo --revision v1 --to did:plc:author \
  --endpoint https://pds.example

# live: apply the writes
lairs publish --repo ./repo --revision v1 --to did:plc:author \
  --endpoint https://pds.example --yes
```

Only `--repo` is required, and `--revision` defaults to `HEAD`. Both `--to` and
`--endpoint` are optional and default to the logged-in session: `--to` falls
back to the session's DID and `--endpoint` to the session's PDS, so after `lairs
login` a publish needs only `--repo`. When `--to` is omitted and no session is
saved, the command errors and exits non-zero.

`--yes` applies the writes instead of only showing the plan. A live publish
needs a target PDS endpoint, from `--endpoint` or the logged-in session, and it
always needs a logged-in session for credentials: `--yes` exits non-zero when
there is neither an endpoint nor a session, and again when no session is logged
in even if `--endpoint` was given. The printed summary counts creates, updates,
and deletes, and a non-empty dry run reminds the caller to pass `--yes
--endpoint` to apply. Writes target only the `--to` repository.

## `inspect`

Load a corpus from a PDS and print a per-record-type count summary.

```bash
lairs inspect at://did:plc:author/pub.layers.corpus.corpus/abc \
  --endpoint https://pds.example
```

The corpus AT-URI is positional and `--endpoint` is required. The output is the
total record count and a count per collection NSID.

## `datasets`

Resolve a handle or DID and list its datasets, one row per corpus.

```bash
lairs datasets alice.example --language en --min-expressions 100
```

The actor (handle or DID) is positional. `--source` chooses the discovery
source (`auto`, `pds`, or `appview`, default `auto`), `--appview` sets the
appview base URL, and `--endpoint` overrides the PDS base URL. The shared facet
flags filter the rows: `--language`, `--domain`, `--license`, `--min-expressions`,
`--max-expressions`, `--text` (a case-insensitive substring over name and
description), and `--has-adjudication` / `--no-has-adjudication`. `--limit`
caps the number of rows and `--json` prints JSON instead of a table.

## `toc`

Resolve a handle or DID and print its repository collection inventory,
starring the dataset-shaped collections, without dumping records.

```bash
lairs toc alice.example --counts
```

The actor is positional. `--source` chooses the discovery source (`auto`,
`pds`, or `appview`, default `auto`) and `--endpoint` overrides the PDS base
URL. `--counts` counts records per collection, which drains each collection.
`--json` prints JSON instead of a table.

## `search`

Fan out over a seed of handles or DIDs and list the matching datasets,
deduplicated by corpus.

```bash
lairs search alice.example bob.example --domain news
```

One or more actors are positional. `--source`, `--appview`, the shared facet
flags (`--language`, `--domain`, `--license`, `--min-expressions`,
`--max-expressions`, `--text`, `--has-adjudication`), `--limit`, and `--json`
behave as for `datasets`.

## `index`

Maintain a local, searchable dataset index in a panproto Repository, built from
a crawl and kept fresh from the firehose. The group has four subcommands.

```bash
lairs index build --into ./index --endpoint https://relay.example
lairs index update --index ./index --relay https://relay.example
lairs index search --index ./index "treebank" --domain news
lairs index diff --index ./index v1 v2
```

`index build` crawls repositories into the index. `--into` and `--endpoint` are
required; `--seed-did` (repeatable) restricts the crawl to specific DIDs (the
default crawls every repo), `--max-repos` bounds the repositories visited, and
`--message` sets the crawl commit message (default `backfill crawl`).

`index update` tails the firehose into an existing index. `--index` and
`--relay` are required; `--limit` stops after that many events.

`index search` searches the local index. `--index` is required and the
free-text query is an optional positional. Filters are `--domain`, `--language`,
`--license`, `--min-expressions`, `--max-expressions`, `--metric` (a required
quality metric slug), and `--min-rounds` (minimum annotation rounds). `--duckdb`
pre-filters through the DuckDB accelerator.

`index diff` diffs the index between two revisions. `--index` is required and
the base and head revisions are positional.

## `tui`

Launch the interactive Textual data explorer: an Explore tab over the discovery
index, a Browse tab over every record type in a local repository, and a Query
tab that runs DuckDB SQL, KWIC concordance, and CQL token-pattern searches over
materialized data.

```bash
lairs tui --index ./index --repo ./repo --data ./views
```

All flags are optional. `--index` opens a discovery index on the Explore tab,
`--repo` opens a local repository on the Browse tab (and feeds the Query tab
unless `--data` is given), and `--data` opens a materialized Parquet directory
on the Query tab. The TUI requires the optional `textual` dependency; when it is
missing the command exits non-zero with a message.

## `login`, `logout`, and `whoami`

Authenticate to a PDS and manage the saved session that the discovery and
publish commands fall back to.

```bash
LAIRS_APP_PASSWORD=... lairs login alice.example
lairs whoami
lairs logout
```

`login` resolves a handle or DID to its PDS, exchanges an app password for a
session, and saves it so later commands authenticate automatically. The
identifier is positional. Prefer the `LAIRS_APP_PASSWORD` environment variable
over `--app-password` so the secret does not appear in the process list;
`--pds` supplies the PDS base URL directly and skips handle resolution. When
neither `--app-password` nor `LAIRS_APP_PASSWORD` is set, `login` exits
non-zero.

`logout` deletes the saved session, if any. `whoami` prints the saved session's
identity, DID, and PDS, and exits non-zero when no session is saved.

## See also

- [Authoring](authoring.md) for the `pull`/`publish` workflow in Python.
- [Dataset API](dataset-api.md) for working with a materialized corpus.
- [Exporters](exporters.md) for turning the materialized views into datasets.
