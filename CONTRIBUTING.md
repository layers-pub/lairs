# Contributing to lairs

Thank you for your interest in improving `lairs`. This document explains how to
set up a development environment, the checks your change must pass, and the
conventions the codebase follows. The same material, with more depth on the
internals, lives in the
[Development section of the documentation](https://layers.pub/lairs/development/).

By participating you agree to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug.** Open an issue with a minimal reproduction, the `lairs`
  version (`python -c "import lairs; print(lairs.__version__)"`), and your
  Python version.
- **Request a feature.** Open an issue describing the use case before writing
  code, so we can agree on scope and shape.
- **Send a pull request.** Bug fixes, new format codecs, new exporters, new
  knowledge-base connectors, documentation, and tests are all welcome.

`lairs` is a client for the [Layers](https://github.com/layers-pub) format. It
never owns data: it reads from and writes to user-controlled Personal Data
Servers, and every local index can be rebuilt from the network. Keep that
principle in mind when proposing changes that touch the data flow.

## Development environment

`lairs` targets **Python 3.14+** and uses [uv](https://docs.astral.sh/uv/) for
environment and dependency management.

```bash
git clone https://github.com/layers-pub/lairs
cd lairs
uv sync          # creates .venv and installs the project with the dev group
```

`uv sync` installs the `dev` dependency group, which pulls in every optional
extra it can on the 3.14 floor so the test suite exercises the integrations
rather than skipping them. TensorFlow has no stable `cp314` wheel yet; install
the nightly (`uv pip install tf-nightly`) to exercise the tfdata exporter, which
CI does on every run. decord and label-studio-sdk have no `cp314` wheel at all,
so a few of their tests skip cleanly until upstream publishes one.

Activate the environment if you prefer running tools directly:

```bash
source .venv/bin/activate
```

Otherwise prefix commands with `uv run` (for example `uv run pytest`).

## The checks your change must pass

Continuous integration runs the commands below on every pull request. Run them
locally before pushing; a green local run is a green CI run.

```bash
uv run ruff format --check lairs tests      # formatting
uv run ruff check lairs tests               # linting (ruff "ALL" ruleset)
uv run ty check --error-on-warning          # static type checking
uv run pytest                               # the unit + functional suite
```

Apply formatting fixes with `uv run ruff format lairs tests`, and let ruff fix
what it safely can with `uv run ruff check --fix lairs tests`.

CI additionally forbids `Any` in annotations via ruff `ANN401`. `Any` is the
unsound escape hatch; annotate precisely with a protocol, a `TypeVar`, or a
concrete union instead. Sound `object` (which must be narrowed before use) is
allowed, and the `ALL` ruleset requires annotating ignored `*args`/`**kwargs`,
for which `object` is the right choice.

### Integration tests

Tests marked `integration` are deselected by default. They run against a local
Personal Data Server started with Docker:

```bash
uv run pytest --run-integration -m integration
```

The fixture brings up the PDS via `tests/pds/docker-compose.yml`, picks a free
port automatically, and skips cleanly when Docker is unavailable. You do not
need Docker for everyday work; the default `pytest` run covers the library
without it.

## Coding conventions

The codebase is uniform on purpose. Match the surrounding code.

- **didactic models everywhere.** Every structured value is a `didactic.Model`.
  Do not introduce dataclasses, `TypedDict`, or `pydantic` for record-shaped
  data.
- **No `Any`** in annotations (enforced in CI via ruff `ANN401`). Prefer precise
  types, protocols, and unions; sound `object` (narrowed before use) is fine.
- **Imports at module top level.** Function- and method-level imports are a ruff
  error (`PLC0415`). The only permitted exception is a genuinely lazy import of
  a heavy optional extra (for example `tensorflow`, `torch`, `datasets`,
  `huggingface_hub`, `webdataset`, `mne`, `soundfile`) that must not be imported
  unless its extra is installed. Never silence the rule with `# noqa` for a
  stdlib, core-dependency, or first-party import.
- **Public API via `__all__`.** Export through `__all__`; prefer named exports.
- **Numpy-style docstrings.** Every public module, class, and function is
  documented. Because didactic models accept `**kwargs`, document model fields
  under an `Attributes` section, not `Parameters` (mkdocstrings/griffe renders
  the former correctly for these models).
- **No em-dashes** in code, comments, docstrings, or documentation. Use commas,
  semicolons, colons, or parentheses.
- **Optional extras are isolated.** Code that needs an extra imports it lazily,
  references it only under `TYPE_CHECKING` for annotations, and fails with a
  clear message when the extra is missing. Register new codecs, exporters, and
  knowledge bases through the entry points in `pyproject.toml`.

## Documentation

Documentation is built with MkDocs and mkdocstrings (numpy docstring style).

```bash
uv run --group docs mkdocs serve     # live preview at http://127.0.0.1:8000
uv run --group docs mkdocs build --strict   # the gate: zero warnings
```

`mkdocs build --strict` must succeed with no warnings. If you add or rename a
public symbol, make sure its docstring renders and that any new page is wired
into the `nav` in `mkdocs.yml`.

## Regenerating record models

The `pub.layers.*` record models in `lairs/records/_generated/` are generated
from vendored Layers lexicons. Do not edit generated files by hand.

```bash
uv run lairs gen            # regenerate models from the vendored lexicons
uv run lairs gen --check    # drift gate: fail if generated output is stale
```

To pull in a new lexicon version, re-vendor with `uv run lairs vendor` (which
updates `MANIFEST.toml`) and then regenerate. See
[Vendoring and codegen](https://layers.pub/lairs/guide/codegen/) for
the full workflow.

## Commit and pull-request conventions

- **Conventional Commits** with a scope where one fits: `feat(tui): ...`,
  `fix: ...`, `docs: ...`, `test: ...`, `refactor(store): ...`.
- **Imperative mood**, no trailing period: "Add the CoNLL-U exporter", not
  "Added ..." or "Adds ...".
- **Never mention AI assistants** in commit messages, and add no `Co-Authored-By`
  trailers.

For a pull request:

1. Branch from `main`.
2. Keep the change focused; add tests for new behaviour and a `CHANGELOG.md`
   entry under `## [Unreleased]` when the change is user-visible.
3. Ensure formatting, lint, type check, the test suite, and a strict docs build
   all pass.
4. Open the PR with a clear description of the motivation and the change.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE) that covers this project.
