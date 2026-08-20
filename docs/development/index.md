# Development

Contributor documentation covers environment setup, required checks, and the
organization of the codebase. To use the library, start with the
[Tutorial](../tutorial/index.md).

[`CONTRIBUTING.md`](https://github.com/layers-pub/lairs/blob/main/CONTRIBUTING.md)
at the repository root provides the abbreviated instructions.

## Environment

`lairs` targets Python 3.14+ and uses [uv](https://docs.astral.sh/uv/) for
environments and dependencies.

```bash
git clone https://github.com/layers-pub/lairs
cd lairs
uv sync
```

`uv sync` creates `.venv` and installs the project together with the `dev`
dependency group. The dev group pulls in every optional extra that has a
`cp314` wheel, so the test suite exercises the integrations rather than skipping
them. TensorFlow has no stable `cp314` wheel yet; install the nightly
(`uv pip install tf-nightly`) to exercise the tfdata exporter, which CI does on
every run. decord and label-studio-sdk have no `cp314` wheel at all, so a few of
their tests skip cleanly until upstream publishes one.

Run tools through `uv run`, or activate the environment and call them directly:

```bash
source .venv/bin/activate
```

## The checks

Continuous integration runs these checks on every push and pull request. Run
them locally before pushing.

```bash
uv run ruff format --check lairs tests           # formatting
uv run ruff check lairs tests                    # lint, the ruff "ALL" ruleset
uvx ty check --python .venv --error-on-warning   # static type checking
uv run pytest                                    # the default suite
```

To apply the available automatic fixes:

```bash
uv run ruff format lairs tests
uv run ruff check --fix lairs tests
```

CI runs one more gate: a search that fails if `Any` or a bare `object` appears
in a type-annotation position anywhere under `lairs/` or `tests/`. Annotate
precisely instead, with a protocol, a `TypeVar`, or a concrete union.

The [Testing](testing.md) page covers the suite, its markers, and the local
Personal Data Server used by the integration tests.

## Project layout

```text
lairs/
├── records/         generated pub.layers.* models, BlobRef, normalization
├── atproto/         PDS access: XRPC, CAR/DAG-CBOR decode, firehose, handles
├── store/           the schema-aware content-addressed repository
├── data/            the Dataset and Corpus API, Arrow/Parquet materialisation
├── author/          builders, blob upload, dependency-ordered publishing
├── media/           audio/video/time-series resolution and anchor resolution
├── discovery/       network crawl, the searchable index, the DuckDB accelerator
├── integrations/    codecs, exporters, knowledge bases, experiment tracking
├── tui/             the Textual explorer (Explore, Discover, Browse, Query)
├── _codegen/        the lexicon-to-model generator behind `lairs gen`
├── lexicons/        the vendored Layers lexicon tree and MANIFEST.toml
└── cli.py           the `lairs` command
```

Tests mirror this tree under `tests/`.

## Conventions

Follow these conventions when adding code:

- **didactic models for all structured data.** No dataclasses, `TypedDict`, or
  `pydantic` for record-shaped values.
- **No `Any` or bare `object` in annotations.** Use a protocol, `TypeVar`,
  `JsonValue`, or a concrete union.
- **Imports at module top level.** Function- or method-level imports are a ruff
  error (`PLC0415`). The only exception is a lazy import of a heavy optional
  extra that must not load unless its extra is installed; never silence the rule
  for a stdlib, core-dependency, or first-party import.
- **Numpy-style docstrings** on every public module, class, and function.
  didactic models take `**kwargs`, so document their fields under `Attributes`,
  not `Parameters`, for mkdocstrings to render them.
- **Public API through `__all__`**, named exports preferred.

## Documentation

MkDocs and mkdocstrings build the documentation from numpy-style docstrings.

```bash
uv run --group docs mkdocs serve            # live preview
uv run --group docs mkdocs build --strict   # the gate: zero warnings
```

`mkdocs build --strict` must finish with no warnings. When you add or rename a
public symbol, confirm its docstring renders, and wire any new page into the
`nav` in `mkdocs.yml`.

## Record models

The `pub.layers.*` models under `lairs/records/_generated/` are generated, not
written. Regenerate them rather than editing them:

```bash
uv run lairs gen           # regenerate from the vendored lexicons
uv run lairs gen --check   # drift gate: fail if the committed models are stale
```

Adopting a new Layers lexicon version is a re-vendor followed by a regenerate.
The [Code generation](codegen.md) page covers the pipeline; the user-facing
walkthrough is [Vendoring and codegen](../guide/codegen.md).

## Releasing

The [Releasing](releasing.md) page covers the version bump, PyPI upload, and
documentation deployment.
