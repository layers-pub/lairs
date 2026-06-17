# CLI

The ``lairs`` console script. The entry point is
``lairs.cli.main(argv=None)``, which parses arguments and dispatches to
the subcommand handlers. For the per-subcommand reference see [Guides >
The CLI](../guide/cli.md).

## Subcommands

- ``lairs vendor --from <path>``: refresh the vendored lexicon tree
  and rewrite ``MANIFEST.toml``.
- ``lairs gen [--check]``: regenerate the record models. ``--check``
  is the drift gate.
- ``lairs pull <did> --endpoint <pds> --into <repo>``: ingest an
  account's records into a local Repository.
- ``lairs materialize <uri> --endpoint <pds> --out <dir>``: write the
  Arrow/Parquet views of a corpus.
- ``lairs publish --repo <dir> --to <did> [--endpoint <pds>] [--yes]``:
  plan or apply the minimal write set, a dry run by default.
- ``lairs inspect <uri> --endpoint <pds>``: print a per-record-type
  count summary.

## Entry point

::: lairs.cli.main
