# Testing

The test suite under `tests/` mirrors the package layout. The default run uses
local data and fixed service responses. Tests that need Docker are opt-in,
and examples needing an unavailable optional extra skip with a reason.

<!-- lairs-test: check reason="developer test selection commands; not nested test runs" -->
```bash
uv run pytest                 # the default suite
uv run pytest tests/store     # one subtree
uv run pytest -k materialize  # by keyword
```

Configuration is in `pyproject.toml` under `[tool.pytest.ini_options]`:
`--import-mode=importlib`, `testpaths = ["tests"]`, and the `integration` and
`documentation` markers.

## Executable documentation

README and documentation Python and shell fences are collected automatically by
the top-level package tests. Every Python or shell fence needs a `lairs-test`
comment immediately above it. A new unclassified example fails the default suite.

The comments select one of three policies:

```text
<!-- lairs-test: run fixture=store -->
<!-- lairs-test: run fixture=audio requires=soundfile -->
<!-- lairs-test: check reason="installation commands are syntax-checked only" -->
<!-- lairs-test: skip reason="interactive template requires caller inputs" -->
```

`run` executes the actual fenced source. Earlier runnable Python blocks on the
same page establish its context in a fresh interpreter and temporary directory;
the named fixture supplies data at the block boundary. `requires` lists optional
import modules, separated by commas. Missing modules skip only the affected
block, whose Python syntax is still checked. Python tracebacks retain the
document path and line number.

`check` compiles Python or runs `bash -n` without executing it. `skip` is reserved
for intentionally partial or interactive templates. Both require a specific
reason. Executable shell examples are restricted to finite `lairs` help commands
and `lairs gen --check`; setup, publishing, and release commands are never run
by the shell gate.
The read-only drift check runs from the source checkout; other runnable examples
use temporary working directories.

Read examples use fixed HTTP responses. Stores, views, codec inputs, media,
and tracking state use temporary fixtures. Live authoring examples use fresh
accounts on the existing Docker PDS fixture, with the endpoint and authenticated
session passed explicitly. They never write to the public Layers PDS or a Hub
account.

Run the documentation subset directly:

<!-- lairs-test: check reason="documentation test commands are not executed recursively" -->
```bash
uv run pytest -m documentation
uv run pytest -m documentation --run-integration
```

CI and the release workflow run the full suite with `--run-integration`, which
includes these examples and their live local-PDS cases. Keep the code fences
executable when changing an API; use a syntax-only policy only when execution
would need caller inputs or perform an operational action.

## Unit and functional tests

The default run requires no external service. Adapters that wrap an optional
extra are tested when that extra is installed and skip with a clear reason when
it is not, so a partial environment can still complete successfully. Because
the `dev` group installs every extra that has a `cp314`
wheel, a full `uv sync` environment exercises nearly all of them.

Round-trip and lazy-import tests follow distinct patterns:

- **Property-based tests** with [Hypothesis](https://hypothesis.works/) cover
  the round-trip codecs, where any valid input must survive an encode/decode
  cycle (for instance `tests/integrations/codecs/test_brat.py` and
  `test_conllu.py`).
- **Lazy-import discipline** is enforced by the `assert_lazy_import` fixture in
  `tests/conftest.py`. It imports a `lairs` module in a clean subprocess and
  fails if a named heavy library leaked into `sys.modules`. Add such a test
  whenever you add an adapter behind an optional extra, so importing the package
  never drags the extra in.

## Recorded HTTP

Tests that exercise a real third-party HTTP API record their traffic with
[pytest-recording](https://github.com/kiwicom/pytest-recording) (VCR
cassettes). The tests replay these cassettes offline and deterministically. The
Hugging Face Hub tests in `tests/integrations/hf/test_hub.py` use this. To refresh a
cassette, delete it and re-run with recording enabled and real credentials;
commit the new cassette with the change.

## Integration tests and the local PDS

Tests marked `integration` are skipped unless you pass `--run-integration`:

<!-- lairs-test: check reason="integration test selection commands; not nested test runs" -->
```bash
uv run pytest --run-integration -m integration   # only the integration tests
uv run pytest --run-integration                   # the whole suite, integration included
```

The flag and the marker are registered in `tests/conftest.py`. The main
integration fixture starts a real [Bluesky PDS](https://github.com/bluesky-social/pds)
with Docker Compose (`tests/pds/docker-compose.yml`), waits for it to come up,
provisions an account, and tears it down afterward. It picks a free port
automatically to avoid collisions with local services and skips cleanly when
Docker is not available. Tests that use this fixture exercise the read/write
path end to end against an actual server rather than a mock.

CI runs the integration job separately from the fast checks; see
`.github/workflows/ci.yml`.

## TUI tests

The Textual explorer has its own fixtures in `tests/tui/conftest.py`. Its tests
drive the app through Textual's `Pilot` interface by mounting the app, sending
key presses, switching tabs and views, and asserting on the rendered widget
tree. They catch interaction regressions (a view that fails to
switch, a query that inserts the wrong text) without a terminal.

## Writing tests

- Put a test next to the code it covers, mirroring the package path.
- Mark anything that needs Docker, the network, or an external service with
  `@pytest.mark.integration`.
- Gate a test that needs an optional extra on that extra, and skip with a reason
  when it is absent, rather than letting it error.
- Tests may assert freely, use magic numbers, and reach into private members;
  the per-file ruff ignores in `pyproject.toml` already allow this under
  `tests/`. The ban on `Any` and bare `object` in annotations still applies.
