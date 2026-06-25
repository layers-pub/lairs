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
- ``lairs pull <did> --endpoint <pds> --into <repo> [--message <msg>]``:
  ingest an account's records into a local Repository. ``--message``
  sets the commit message of the pulled snapshot (default
  ``pull layers records``).
- ``lairs materialize <uri> --endpoint <pds> --out <dir>``: write the
  Arrow/Parquet views of a corpus.
- ``lairs publish --repo <dir> [--revision <rev>] [--to <did>]
  [--endpoint <pds>] [--yes]``: plan or apply the minimal write set, a
  dry run by default. ``--revision`` selects which Repository revision
  to publish (default ``HEAD``); ``--to`` defaults to the logged-in
  account's DID.
- ``lairs inspect <uri> --endpoint <pds>``: print a per-record-type
  count summary.
- ``lairs datasets <actor>``: resolve a handle or DID and list its
  datasets, one row per corpus.
- ``lairs toc <actor>``: resolve a handle or DID and print its
  repository collection inventory.
- ``lairs search <actor>...``: fan out over a seed of handles or DIDs
  and list matching datasets.
- ``lairs index <build|update|search|diff>``: build, refresh, search,
  and diff a local dataset index.
- ``lairs tui``: launch the interactive terminal data explorer.
- ``lairs login <identifier>``: authenticate to a PDS with an app
  password and save the session.
- ``lairs logout``: forget the saved session.
- ``lairs whoami``: print the saved session's identity.

## Entry point

::: lairs.cli.main
