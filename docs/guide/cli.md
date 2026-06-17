# The `lairs` command-line interface

This guide covers the `lairs` command and its subcommands: `vendor`, `gen`
(and `gen --check`), `pull`, `materialize`, `publish`, and `inspect`. The CLI is
built on the standard-library `argparse`, so it adds no command-line dependency.
Each subcommand dispatches to a finished component call.

Run `lairs` with no subcommand to print help. Each subcommand has its own
`--help`.

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

Load a corpus from a PDS and write its normalised Arrow/Parquet views.

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

`--repo` and `--to` are required, and `--revision` defaults to `HEAD`. `--yes`
applies the writes and requires `--endpoint`. Passing `--yes` without `--endpoint`
exits non-zero. The printed summary counts creates, updates, and deletes, and a
non-empty dry run reminds the caller to pass `--yes --endpoint` to apply. Writes
target only the `--to` repository.

## `inspect`

Load a corpus from a PDS and print a per-record-type count summary.

```bash
lairs inspect at://did:plc:author/pub.layers.corpus.corpus/abc \
  --endpoint https://pds.example
```

The corpus AT-URI is positional and `--endpoint` is required. The output is the
total record count and a count per collection NSID.

## See also

- [Authoring](authoring.md) for the `pull`/`publish` workflow in Python.
- [Dataset API](dataset-api.md) for working with a materialised corpus.
- [Exporters](exporters.md) for turning the materialised views into datasets.
