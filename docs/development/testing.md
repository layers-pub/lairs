# Testing

The test suite lives under `tests/`, mirroring the package layout. The default
run is fast and dependency-free; everything that needs a network, Docker, or a
heavy optional extra is opt-in or skips cleanly.

```bash
uv run pytest                 # the default suite
uv run pytest tests/store     # one subtree
uv run pytest -k materialize  # by keyword
```

Configuration is in `pyproject.toml` under `[tool.pytest.ini_options]`:
`--import-mode=importlib`, `testpaths = ["tests"]`, and the `integration`
marker.

## Unit and functional tests

The default run covers the library without any external service. Adapters that
wrap an optional extra are tested when that extra is installed and skip with a
clear reason when it is not, so a partial environment still produces a green,
honest run. Because the `dev` group installs every extra that has a `cp314`
wheel, a full `uv sync` environment exercises nearly all of them.

Two patterns appear throughout:

- **Property-based tests** with [Hypothesis](https://hypothesis.works/) cover
  the round-trip codecs, where any valid input must survive an encode/decode
  cycle (for example `tests/integrations/codecs/test_brat.py` and
  `test_conllu.py`).
- **Lazy-import discipline** is enforced by the `assert_lazy_import` fixture in
  `tests/conftest.py`. It imports a `lairs` module in a clean subprocess and
  fails if a named heavy library leaked into `sys.modules`. Add such a test
  whenever you add an adapter behind an optional extra, so importing the package
  never drags the extra in.

## Recorded HTTP

Tests that exercise a real third-party HTTP API record their traffic with
[pytest-recording](https://github.com/kiwicom/pytest-recording) (VCR
cassettes), so they replay offline and deterministically. The Hugging Face Hub
tests in `tests/integrations/hf/test_hub.py` use this. To refresh a cassette,
delete it and re-run with recording enabled and real credentials; commit the new
cassette with the change.

## Integration tests and the local PDS

Tests marked `integration` are deselected unless you pass `--run-integration`:

```bash
uv run pytest --run-integration -m integration   # only the integration tests
uv run pytest --run-integration                   # the whole suite, integration included
```

The flag and the marker are registered in `tests/conftest.py`. The headline
integration fixture starts a real [Bluesky PDS](https://github.com/bluesky-social/pds)
with Docker Compose (`tests/pds/docker-compose.yml`), waits for it to come up,
provisions an account, and tears it down afterward. It picks a free port
automatically, so it does not collide with anything already listening locally,
and it skips cleanly when Docker is not available. This is what lets the
read/write path be tested end-to-end against an actual server rather than a
mock.

CI runs the integration job separately from the fast checks; see
`.github/workflows/ci.yml`.

## TUI tests

The Textual explorer has its own fixtures in `tests/tui/conftest.py` and is
tested by driving the app through Textual's `Pilot` interface: mounting the app,
sending key presses, switching tabs and views, and asserting on the rendered
widget tree. These tests catch interaction regressions (a view that fails to
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
