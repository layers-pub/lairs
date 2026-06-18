"""Shared pytest configuration for the lairs test suite.

Adds a ``--run-integration`` flag and an ``integration`` marker. Integration
tests are deselected by default so that ``uv run pytest`` exercises only the
fast, dependency-free unit tests; passing ``--run-integration`` opts in.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import didactic.api as dx
import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from contextlib import AbstractContextManager

    from lairs._types import JsonValue


@pytest.fixture
def assert_lazy_import() -> Callable[..., None]:
    """Return a probe that verifies lazy-import discipline in a fresh interpreter.

    The probe imports the named lairs module (or modules) in a clean subprocess
    and fails if any of the named heavy libraries ended up in ``sys.modules``.
    Running in a subprocess makes the assertion independent of whatever other
    tests in this process have already imported, which matters now that the dev
    environment installs every optional extra (a library pulled in transitively
    by one adapter must not make another adapter's discipline test flaky).

    Returns
    -------
    collections.abc.Callable
        A callable ``probe(modules, *libraries)`` where ``modules`` is a module
        name or sequence of names to import and ``libraries`` are the modules
        that importing them must not pull into ``sys.modules``.
    """

    def probe(modules: str | Sequence[str], /, *libraries: str) -> None:
        names = (modules,) if isinstance(modules, str) else tuple(modules)
        imports = "\n".join(f"import {name}" for name in names)
        code = (
            f"{imports}\n"
            "import sys\n"
            f"_leaked = [lib for lib in {list(libraries)!r} if lib in sys.modules]\n"
            "raise SystemExit('; '.join(_leaked) if _leaked else 0)"
        )
        completed = subprocess.run(  # noqa: S603  # test-controlled probe code
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )
        detail = completed.stdout.strip() or completed.stderr.strip()
        assert completed.returncode == 0, f"eagerly imported: {detail}"

    return probe


@pytest.fixture(autouse=True)
def _isolated_session_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Redirect the auth session store to a throwaway path for every test.

    Keeps tests hermetic and stops them from reading or overwriting the
    developer's real lairs session file.
    """
    session_file = tmp_path_factory.mktemp("auth") / "session.json"
    monkeypatch.setenv("LAIRS_AUTH_FILE", str(session_file))


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--run-integration`` command-line flag."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests (real IO, optional deps, credentials)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``integration`` marker."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests "
        "(deselected unless --run-integration is given)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: Iterable[pytest.Item],
) -> None:
    """Skip integration tests unless ``--run-integration`` was passed."""
    if config.getoption("--run-integration"):
        return

    skip = pytest.mark.skip(reason="need --run-integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


_PDS_COMPOSE = Path(__file__).parent / "pds" / "docker-compose.yml"
_PDS_PORT = int(os.environ.get("LAIRS_PDS_PORT", "3000"))
_PDS_ENDPOINT = f"http://localhost:{_PDS_PORT}"
_PDS_HEALTH_TIMEOUT_S = 90.0


class PdsServer(dx.Model):
    """Connection details for a running local PDS test instance.

    Parameters
    ----------
    endpoint : str
        The base URL of the running PDS.
    did : str
        The DID of the throwaway account created for the test session.
    handle : str
        The account handle.
    password : str
        The account password.
    access_jwt : str
        The access token authorising writes to the account's repository.
    admin_password : str
        The PDS admin password generated for this session.
    """

    endpoint: str = dx.field(description="base URL of the running PDS")
    did: str = dx.field(description="DID of the throwaway test account")
    handle: str = dx.field(description="account handle")
    password: str = dx.field(description="account password")
    access_jwt: str = dx.field(description="access token authorising writes")
    admin_password: str = dx.field(description="PDS admin password for the session")


def _docker_available() -> bool:
    """Return whether a docker CLI with a reachable daemon is present."""
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"],  # noqa: S607
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


def _compose(
    args: Iterable[str],
    env: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    """Run a docker compose subcommand against the PDS compose file.

    Parameters
    ----------
    args : collections.abc.Iterable of str
        The compose subcommand and its arguments.
    env : dict of str to str
        The environment to run the subcommand under.

    Returns
    -------
    subprocess.CompletedProcess
        The completed process, with output captured.
    """
    return subprocess.run(  # noqa: S603
        ["docker", "compose", "-f", str(_PDS_COMPOSE), *args],  # noqa: S607
        capture_output=True,
        check=False,
        env=env,
    )


def _wait_healthy(endpoint: str, timeout: float) -> bool:
    """Poll the PDS health endpoint until it responds or the timeout elapses.

    Parameters
    ----------
    endpoint : str
        The PDS base URL.
    timeout : float
        The maximum number of seconds to wait.

    Returns
    -------
    bool
        ``True`` if the health endpoint returned 200 within the timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{endpoint}/xrpc/_health", timeout=5.0)
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code == httpx.codes.OK:
            return True
        time.sleep(2.0)
    return False


def _create_account(endpoint: str, admin_password: str) -> PdsServer:
    """Create a throwaway account on the PDS and return its connection details.

    Parameters
    ----------
    endpoint : str
        The PDS base URL.
    admin_password : str
        The PDS admin password generated for this session.

    Returns
    -------
    PdsServer
        The connection details, including the account DID and access token.
    """
    token = secrets.token_hex(8)
    handle = f"u{token}.test"
    password = secrets.token_hex(16)
    response = httpx.post(
        f"{endpoint}/xrpc/com.atproto.server.createAccount",
        json={
            "handle": handle,
            "email": f"{token}@example.test",
            "password": password,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    return PdsServer(
        endpoint=endpoint,
        did=str(body["did"]),
        handle=str(body.get("handle", handle)),
        password=password,
        access_jwt=str(body["accessJwt"]),
        admin_password=admin_password,
    )


@pytest.fixture(scope="session")
def pds_server() -> Iterator[PdsServer]:
    """Yield a running local PDS with a throwaway account, or skip cleanly.

    The fixture starts the PDS container defined in ``tests/pds``, waits for it
    to become healthy, and creates a throwaway account. It skips, rather than
    fails, when docker, the image, or the health check are unavailable, so the
    integration tests degrade cleanly in environments without docker.

    Yields
    ------
    PdsServer
        The connection details for the running PDS.
    """
    if not _docker_available():
        pytest.skip("docker is not available")
    admin_password = secrets.token_hex(16)
    env = {
        **os.environ,
        "PDS_JWT_SECRET": secrets.token_hex(16),
        "PDS_ADMIN_PASSWORD": admin_password,
        "PDS_PLC_ROTATION_KEY_K256_PRIVATE_KEY_HEX": secrets.token_hex(32),
    }
    started = _compose(["up", "-d"], env)
    if started.returncode != 0:
        detail = started.stderr.decode()[:300]
        pytest.skip(f"could not start the pds container: {detail}")
    try:
        if not _wait_healthy(_PDS_ENDPOINT, _PDS_HEALTH_TIMEOUT_S):
            pytest.skip("the pds container did not become healthy in time")
        try:
            server = _create_account(_PDS_ENDPOINT, admin_password)
        except httpx.HTTPError as exc:
            pytest.skip(f"could not create a test account: {exc}")
        yield server
    finally:
        _compose(["down", "-v"], env)


type RouteHandler = Callable[[str, dict[str, str]], tuple[int, JsonValue]]
"""A loopback route callable mapping a request path and query to a response.

Given the request path and parsed query parameters, the callable returns an
HTTP status code and a JSON-serialisable response body.
"""


def _handler_class(routes: RouteHandler) -> type[BaseHTTPRequestHandler]:
    """Build a request-handler class that dispatches GET requests to ``routes``.

    Parameters
    ----------
    routes : RouteHandler
        The route callable to dispatch each GET request to.

    Returns
    -------
    type[http.server.BaseHTTPRequestHandler]
        A handler class bound to ``routes`` over a closure.
    """

    class _Handler(BaseHTTPRequestHandler):
        """A GET-only handler that serialises route results as JSON."""

        def do_GET(self) -> None:  # the stdlib dispatches GET to this name
            """Dispatch a GET request and write the JSON response."""
            split = urlsplit(self.path)
            query = {key: values[0] for key, values in parse_qs(split.query).items()}
            status, body = routes(split.path, query)
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: str) -> None:  # noqa: A002
            """Discard per-request logging to keep test output quiet."""
            _ = (format, args)

    return _Handler


@contextlib.contextmanager
def _serve_routes(routes: RouteHandler) -> Iterator[str]:
    """Serve GET routes on a loopback HTTP server for the block's duration.

    Parameters
    ----------
    routes : RouteHandler
        The route callable backing the server.

    Yields
    ------
    str
        The base URL of the running server.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_class(routes))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


@pytest.fixture
def route_server() -> Callable[[RouteHandler], AbstractContextManager[str]]:
    """Return a factory that serves GET routes on a loopback HTTP server.

    Returns
    -------
    collections.abc.Callable
        A context-manager factory; calling it with a route callable yields the
        base URL of a running loopback server.
    """
    return _serve_routes
