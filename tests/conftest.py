"""Shared pytest configuration for the lairs test suite.

Adds a ``--run-integration`` flag and an ``integration`` marker. Integration
tests are skipped by default; passing ``--run-integration`` opts in.
Annotated documentation examples use temporary data and fixed service responses.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import wave
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Self, override
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import didactic.api as dx
import dns.resolver
import httpx
import libipld
import pyarrow as pa
import pytest
from multiformats import CID, multihash

from lairs._types import JsonValue
from lairs.atproto._car import IpldValue, json_to_ipld, record_cid
from lairs.atproto.blobs import BlobBytes
from lairs.atproto.pds import PdsClient, RecordEnvelope, decode
from lairs.author import LayerBuilder, span
from lairs.conllu.projection import Projector
from lairs.conllu.text import parse
from lairs.data.corpus import Corpus
from lairs.integrations.codecs.conllu import _ConlluSentence, _parse_conllu
from lairs.integrations.kb.glazing import GlazingKB, XrefLinks
from lairs.media.resolve import MediaHandle
from lairs.records._generated.expression import Expression
from lairs.records._generated.media import Media
from lairs.records.blobref import BlobRef
from lairs.store.pool import ModelPool
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from contextlib import AbstractContextManager
    from types import TracebackType


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
_PDS_HEALTH_TIMEOUT_S = 90.0


def _pds_port() -> int:
    """Return the PDS port: an explicit ``LAIRS_PDS_PORT`` or a free one.

    Binding the published, listen, and advertised port to one value keeps the
    endpoint the PDS writes into its DID document equal to the one the host
    reaches it on. Choosing a free port by default lets the integration suite
    run even when another service already holds the conventional 3000.
    """
    override = os.environ.get("LAIRS_PDS_PORT")
    if override:
        return int(override)
    with socket.socket() as probe:
        probe.bind(("", 0))
        return int(probe.getsockname()[1])


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
    port = _pds_port()
    endpoint = f"http://localhost:{port}"
    admin_password = secrets.token_hex(16)
    env = {
        **os.environ,
        "LAIRS_PDS_PORT": str(port),
        "PDS_JWT_SECRET": secrets.token_hex(16),
        "PDS_ADMIN_PASSWORD": admin_password,
        "PDS_PLC_ROTATION_KEY_K256_PRIVATE_KEY_HEX": secrets.token_hex(32),
    }
    started = _compose(["up", "-d"], env)
    if started.returncode != 0:
        detail = started.stderr.decode()[:300]
        pytest.skip(f"could not start the pds container: {detail}")
    try:
        if not _wait_healthy(endpoint, _PDS_HEALTH_TIMEOUT_S):
            pytest.skip("the pds container did not become healthy in time")
        try:
            server = _create_account(endpoint, admin_password)
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

        def _dispatch(self, extra: dict[str, str]) -> None:
            """Dispatch the request to ``routes`` and write the JSON response."""
            split = urlsplit(self.path)
            query = {key: values[0] for key, values in parse_qs(split.query).items()}
            status, body = routes(split.path, {**query, **extra})
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # the stdlib dispatches GET to this name
            """Dispatch a GET request and write the JSON response."""
            self._dispatch({})

        def do_POST(self) -> None:  # the stdlib dispatches POST to this name
            """Dispatch a POST request, exposing the body under ``__body``."""
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length).decode() if length else ""
            self._dispatch({"__body": body})

        @override
        def log_message(self, format: str, *args: str) -> None:
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


def _car_cid(value: object) -> bytes:
    """Compute the raw CIDv1 dag-cbor bytes for a block value."""
    raw = libipld.encode_dag_cbor(value)
    return bytes(CID("base32", 1, "dag-cbor", multihash.digest(raw, "sha2-256")))


def _car_varint(number: int) -> bytes:
    """Encode an unsigned integer as an LEB128 varint for CAR framing."""
    out = bytearray()
    while True:
        chunk = number & 0x7F
        number >>= 7
        out.append(chunk | 0x80 if number else chunk)
        if not number:
            return bytes(out)


def _car_mst_entry(previous: bytes, key: bytes, value_cid: bytes) -> dict[str, object]:
    """Build a prefix-compressed MST entry relative to the previous key."""
    shared = 0
    for left, current in zip(previous, key, strict=False):
        if left != current:
            break
        shared += 1
    return {"p": shared, "k": key[shared:], "v": value_cid, "t": None}


def _build_repo_car(did: str, keys: Sequence[str]) -> bytes:
    """Build a minimal repository CAR from a repo DID and sorted MST keys.

    Returns ``com.atproto.sync.getRepo`` CAR bytes: a signed commit pointing at
    a single MST node whose entries carry the given ``collection/rkey`` keys.
    Record value blocks are deliberately omitted, since the counting path walks
    the tree without resolving them.
    """
    previous = b""
    entries: list[object] = []
    for key in keys:
        key_bytes = key.encode()
        entries.append(_car_mst_entry(previous, key_bytes, _car_cid({"rk": key})))
        previous = key_bytes
    node = {"l": None, "e": entries}
    node_cid = _car_cid(node)
    commit = {
        "version": 3,
        "did": did,
        "data": node_cid,
        "rev": "aaaaaaaaaaaaa",
        "prev": None,
    }
    commit_cid = _car_cid(commit)
    header = libipld.encode_dag_cbor({"roots": [commit_cid], "version": 1})
    car = bytearray(_car_varint(len(header)) + header)
    for cid, value in ((commit_cid, commit), (node_cid, node)):
        block = cid + libipld.encode_dag_cbor(value)
        car += _car_varint(len(block)) + block
    return bytes(car)


@pytest.fixture
def make_repo_car() -> Callable[[str, Sequence[str]], bytes]:
    """Return a builder for a minimal repository CAR from full MST keys.

    Returns
    -------
    collections.abc.Callable
        A function ``(did, keys) -> bytes``; see :func:`_build_repo_car`.
    """
    return _build_repo_car


# fixtures for executable documentation examples.


_DOC_TIMESTAMP = "2026-01-01T00:00:00Z"
_DOC_TEXT = "The cat sat on the mat."
_DOC_CONLLU = (
    "# sent_id = cats-1\n"
    "# text = The cat sat\n"
    "1\tThe\tthe\tDET\tDT\t_\t2\tdet\t2:det\t_\n"
    "2\tcat\tcat\tNOUN\tNN\tNumber=Sing\t3\tnsubj\t3:nsubj\t_\n"
    "3\tsat\tsit\tVERB\tVBD\tTense=Past\t0\troot\t0:root\t_\n\n"
)
_DOC_PDS = "https://pds.example"
_DOC_DEFAULT_DID = "did:plc:author"
_DOC_CORPUS_KEYS = ("cats-en", "abc", "92cfd1034bcef513c2796962", "3k...")


type DocumentationValue = (
    JsonValue
    | bytes
    | Path
    | dx.Model
    | type[dx.Model]
    | Corpus
    | Repository
    | PdsClient
    | httpx.Client
    | pa.Table
    | _ConlluSentence
    | tuple[dx.Model, ...]
    | tuple[tuple[str, dx.Model], ...]
    | Callable[[], tuple[Expression, ...]]
    | Callable[[RecordEnvelope, type[dx.Model]], dx.Model]
)
"""The concrete fixture values exposed to documentation examples."""


class DocumentationConfig(dx.Model):
    """Paths and optional loopback PDS details for one isolated example.

    Attributes
    ----------
    project_root : str
        Source checkout whose examples are being tested.
    work_dir : str
        Disposable working directory for all example output.
    document_path : str
        Repository-relative Markdown path.
    pds : PdsServer or None
        A fresh throwaway account on the local Docker PDS, when needed.
    """

    project_root: str = dx.field(description="source checkout")
    work_dir: str = dx.field(description="disposable example directory")
    document_path: str = dx.field(description="repository-relative Markdown path")
    pds: dx.Embed[PdsServer] | None = dx.field(
        default=None,
        description="fresh loopback PDS account",
    )


@pytest.fixture
def documentation_config_factory(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Callable[[str, bool], DocumentationConfig]:
    """Return isolated documentation configs, provisioning PDS only on demand.

    Returns
    -------
    collections.abc.Callable
        Factory receiving the document path and whether live writes are needed.
    """

    def config(document_path: str, needs_pds: bool) -> DocumentationConfig:  # noqa: FBT001 - fixture factory receives metadata, not boolean literals
        server = None
        if needs_pds:
            running = request.getfixturevalue("pds_server")
            if not isinstance(running, PdsServer):
                msg = "documentation writes require the local PDS fixture"
                raise TypeError(msg)
            if urlsplit(running.endpoint).hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                msg = "documentation writes are restricted to loopback"
                raise ValueError(msg)
            server = _create_account(running.endpoint, running.admin_password)
        return DocumentationConfig(
            project_root=str(Path(__file__).resolve().parents[1]),
            work_dir=str(tmp_path),
            document_path=document_path,
            pds=server,
        )

    return config


def _documentation_wav() -> bytes:
    """Return a three-second mono WAV without loading an optional decoder."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(1000)
        writer.writeframes(b"\0\0" * 3000)
    return buffer.getvalue()


def _documentation_records(did: str) -> tuple[RecordEnvelope, ...]:
    """Build a coherent small corpus under an arbitrary illustrative DID."""
    prefix = f"at://{did}"
    expression_uri = f"{prefix}/pub.layers.expression.expression/abc123"
    expression: dict[str, JsonValue] = {
        "$type": "pub.layers.expression.expression",
        "id": "doc-0001",
        "kind": "sentence",
        "createdAt": _DOC_TIMESTAMP,
        "text": _DOC_TEXT,
        "languages": ["en"],
        "anchor": {"textSpan": {"byteStart": 0, "byteEnd": 23}},
    }
    layer: dict[str, JsonValue] = {
        "$type": "pub.layers.annotation.annotationLayer",
        "expression": expression_uri,
        "kind": "token-tag",
        "subkind": "pos",
        "createdAt": _DOC_TIMESTAMP,
        "annotations": [
            {
                "uuid": {"value": "11111111-1111-4111-8111-111111111111"},
                "label": "DET",
                "tokenIndex": 0,
                "anchor": {"textSpan": {"byteStart": 0, "byteEnd": 3}},
            },
            {
                "uuid": {"value": "22222222-2222-4222-8222-222222222222"},
                "label": "NOUN",
                "tokenIndex": 1,
                "anchor": {"textSpan": {"byteStart": 4, "byteEnd": 7}},
            },
        ],
    }
    pairs: list[tuple[str, dict[str, JsonValue]]] = [
        (expression_uri, expression),
        (f"{prefix}/pub.layers.annotation.annotationLayer/lay123", layer),
    ]
    for index, key in enumerate(_DOC_CORPUS_KEYS):
        corpus_uri = f"{prefix}/pub.layers.corpus.corpus/{key}"
        pairs.append(
            (
                corpus_uri,
                {
                    "$type": "pub.layers.corpus.corpus",
                    "name": "Cats corpus",
                    "createdAt": _DOC_TIMESTAMP,
                },
            )
        )
        pairs.append(
            (
                f"{prefix}/pub.layers.corpus.membership/m{index}",
                {
                    "$type": "pub.layers.corpus.membership",
                    "corpusRef": corpus_uri,
                    "expressionRef": expression_uri,
                    "createdAt": _DOC_TIMESTAMP,
                    "split": "dev",
                },
            )
        )
    return tuple(
        RecordEnvelope(uri=uri, cid=record_cid(value), value=value)
        for uri, value in pairs
    )


def _documentation_car(did: str, records: tuple[RecordEnvelope, ...]) -> bytes:
    """Encode a complete CAR whose MST references every record-value block."""
    blocks: dict[bytes, IpldValue] = {}
    entries: list[IpldValue] = []
    previous = b""
    for envelope in sorted(records, key=lambda item: item.uri):
        key = envelope.uri.removeprefix(f"at://{did}/").encode()
        value = json_to_ipld(envelope.value)
        cid = bytes(CID.decode(envelope.cid))
        blocks[cid] = value
        shared = 0
        for left, right in zip(previous, key, strict=False):
            if left != right:
                break
            shared += 1
        entries.append({"p": shared, "k": key[shared:], "v": cid, "t": None})
        previous = key
    node: dict[str, IpldValue] = {"l": None, "e": entries}
    node_cid = _car_cid(node)
    blocks[node_cid] = node
    commit: dict[str, IpldValue] = {
        "version": 3,
        "did": did,
        "data": node_cid,
        "rev": "3kdocfixture",
        "prev": None,
    }
    commit_cid = _car_cid(commit)
    blocks[commit_cid] = commit
    header = libipld.encode_dag_cbor({"version": 1, "roots": [commit_cid]})
    result = bytearray(_car_varint(len(header)) + header)
    for cid, value in blocks.items():
        block = cid + libipld.encode_dag_cbor(value)
        result.extend(_car_varint(len(block)) + block)
    return bytes(result)


class _DocumentationCrossReferences:
    """A Glazing fixture that never creates a home-directory cache."""

    def resolve(self, ref: str, *, source: str) -> XrefLinks:
        """Return deterministic lexical links for the documented example."""
        _ = (ref, source)
        return {"verbnet_classes": ["give-13.1"], "framenet_frames": ["Giving"]}


def _documentation_xrefs(_kb: GlazingKB) -> _DocumentationCrossReferences:
    """Return the fixture cross-reference boundary for a connector."""
    return _DocumentationCrossReferences()


class DocumentationRuntime:
    """Own temporary fixtures and service boundaries for one subprocess.

    Parameters
    ----------
    config : DocumentationConfig
        Disposable paths and optional local-PDS connection details.
    """

    def __init__(self, config: DocumentationConfig) -> None:
        self.config = config
        self._stack = contextlib.ExitStack()
        self._seen: set[str] = set()
        self._bindings: dict[str, DocumentationValue] = {}
        self._did = config.pds.did if config.pds is not None else _DOC_DEFAULT_DID
        self._audio = _documentation_wav()
        self._cid = str(
            CID("base32", 1, "raw", multihash.digest(self._audio, "sha2-256"))
        )
        self._records: dict[str, tuple[RecordEnvelope, ...]] = {}

    def __enter__(self) -> Self:
        """Install deterministic boundaries and seed local model fixtures."""
        original = httpx.HTTPTransport.handle_request

        def route(
            transport: httpx.HTTPTransport, request: httpx.Request
        ) -> httpx.Response:
            if request.url.host in {"localhost", "127.0.0.1", "::1"}:
                server = self.config.pds
                if (
                    server is None
                    or request.url.port != httpx.URL(server.endpoint).port
                ):
                    msg = f"unexpected loopback request in documentation: {request.url}"
                    raise RuntimeError(msg)
                return original(transport, request)
            return self._route(request)

        self._guard_sockets()
        self._stack.enter_context(
            patch.object(httpx.HTTPTransport, "handle_request", route)
        )
        self._stack.enter_context(
            patch("dns.resolver.resolve", side_effect=dns.resolver.NXDOMAIN)
        )
        self._stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "WANDB_MODE": "disabled",
                    "WANDB_SILENT": "true",
                    "GLAZING_SKIP_INIT_CHECK": "1",
                    "MLFLOW_TRACKING_URI": (
                        Path(self.config.work_dir) / "mlruns"
                    ).as_uri(),
                },
            )
        )
        self._base()
        return self

    def _guard_sockets(self) -> None:
        """Prevent fixture gaps from reaching external sockets or DNS."""
        original_lookup = socket.getaddrinfo
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        loopback = {
            "localhost",
            "127.0.0.1",
            "::1",
            b"localhost",
            b"127.0.0.1",
            b"::1",
            None,
        }

        def lookup(
            host: str | bytes | None,
            port: str | int | None,
            *args: int,
            **kwargs: int,
        ) -> Sequence[
            tuple[
                int,
                int,
                int,
                str,
                tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
            ]
        ]:
            if host not in loopback:
                msg = f"external DNS is disabled in documentation examples: {host!r}"
                raise RuntimeError(msg)
            return original_lookup(host, port, *args, **kwargs)

        def check_address(
            address: tuple[str, int] | tuple[str, int, int, int] | str | bytes,
        ) -> None:
            if isinstance(address, tuple) and address[0] in loopback:
                return
            if isinstance(address, str) and Path(address).resolve().is_relative_to(
                Path(self.config.work_dir)
            ):
                return
            msg = (
                f"external sockets are disabled in documentation examples: {address!r}"
            )
            raise RuntimeError(msg)

        def connect(
            connection: socket.socket,
            address: tuple[str, int] | tuple[str, int, int, int] | str | bytes,
        ) -> None:
            check_address(address)
            original_connect(connection, address)

        def connect_ex(
            connection: socket.socket,
            address: tuple[str, int] | tuple[str, int, int, int] | str | bytes,
        ) -> int:
            check_address(address)
            return original_connect_ex(connection, address)

        self._stack.enter_context(patch("socket.getaddrinfo", lookup))
        self._stack.enter_context(patch.object(socket.socket, "connect", connect))
        self._stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore patched boundaries and close every fixture-owned client."""
        self._stack.__exit__(exc_type, exc, traceback)

    def _repo_records(self, did: str) -> tuple[RecordEnvelope, ...]:
        """Return cached records for the requested illustrative authority."""
        if did not in self._records:
            self._records[did] = _documentation_records(did)
        return self._records[did]

    def _base(self) -> None:
        """Seed shared corpus, repository, codec, and Arrow examples once."""
        records = self._repo_records(self._did)
        expression = decode(records[0], Expression)
        builder = LayerBuilder(
            records[0].uri, "token-tag", expression.createdAt, subkind="pos"
        )
        builder.add(anchor=span(0, 3), label="DET", token_index=0)
        builder.add(anchor=span(4, 7), label="NOUN", token_index=1)
        layer = builder.build()
        expression_uri = records[0].uri
        layer_uri = records[1].uri
        corpus_uri = f"at://{self._did}/pub.layers.corpus.corpus/cats-en"
        pool = ModelPool()
        pool.add(expression_uri, expression)
        pool.add(layer_uri, layer)
        corpus = Corpus(pool, uri=corpus_uri)
        root = Path(self.config.work_dir)
        repository = Repository.init(root / "example-repo")
        repository.save(expression_uri, expression)
        repository.save(layer_uri, layer)
        revision = repository.commit("seed documentation example")
        repository.tag("v1", revision=revision)
        http = self._stack.enter_context(httpx.Client())
        client = self._stack.enter_context(PdsClient(_DOC_PDS, http))
        self._bindings.update(
            {
                "repo_did": self._did,
                "corpus_uri": corpus_uri,
                "expression_uri": expression_uri,
                "expr_uri": expression_uri,
                "layer_uri": layer_uri,
                "some_at_uri": expression_uri,
                "expression": expression,
                "published_expression": records[0],
                "layer": layer,
                "corpus": corpus,
                "repo": repository,
                "Expression": Expression,
                "model": Expression,
                "client": client,
                "envelopes": (records[0],),
                "other_envelopes": (records[1],),
                "expressions": (expression,),
                "layer_pairs": ((layer_uri, layer),),
                "decode": decode,
                "audio_bytes": self._audio,
                "cid": self._cid,
                "blob": BlobBytes(
                    did=self._did,
                    cid=self._cid,
                    data=self._audio,
                    mime_type="audio/wav",
                ),
                "cache_root": root / "blob-cache",
                "anchor": span(0, 3),
                "text": _DOC_CONLLU,
                "conllu_text": _DOC_CONLLU,
                "parsed_sentence": _parse_conllu(_DOC_CONLLU),
                "txt": "John works at Acme.",
                "ann": (
                    "T1\tPER 0 4\tJohn\nT2\tORG 14 18\tAcme\n"
                    "R1\temployed Arg1:T1 Arg2:T2\n"
                ),
            }
        )

        def fetch_expressions() -> tuple[Expression, ...]:
            return (expression,)

        self._bindings["fetch_expressions"] = fetch_expressions
        self._bindings["table"] = pa.table(
            {
                "tokens": [["The", "cat"]],
                "labels": [["DET", "NOUN"]],
                "token_index": [0],
                "label": ["DET"],
                "byte_start": [0],
                "byte_end": [3],
                "uri": [expression_uri],
                "media": [self._audio],
            }
        )
        corpus.materialize(root / "materialized")
        (root / "en_ewt-ud-train.conllu").write_text(_DOC_CONLLU, encoding="utf-8")

    def setup(self, profile: str) -> dict[str, DocumentationValue]:
        """Return initial bindings once and explicit per-block fixture overrides."""
        allowed = {
            "core",
            "temporary-cwd",
            "pds-read",
            "tutorial-corpus",
            "corpus",
            "store",
            "codec",
            "exporters",
            "hub-recording",
            "knowledge-bases",
            "query-views",
            "conllu-store",
            "tracking",
            "media-blob",
            "text-anchor",
            "audio",
            "video",
            "neural",
            "authoring-pds",
            "cli-local",
            "codegen-check",
        }
        if profile not in allowed:
            msg = f"unknown documentation fixture profile: {profile}"
            raise ValueError(msg)
        result = dict(self._bindings) if not self._seen else {}
        if profile in {"media-blob", "audio", "video", "neural", "text-anchor"}:
            result.update(self._media(profile))
        if profile == "authoring-pds":
            result.update(self._authoring())
        if profile == "knowledge-bases" and profile not in self._seen:
            self._knowledge()
        if profile == "hub-recording" and profile not in self._seen:
            self._hub()
        if profile == "conllu-store" and profile not in self._seen:
            self._conllu()
        self._seen.add(profile)
        return result

    def _authoring(self) -> dict[str, DocumentationValue]:
        """Return a fresh authenticated loopback account's explicit inputs."""
        server = self.config.pds
        if server is None:
            msg = "authoring documentation requires the Docker PDS fixture"
            raise RuntimeError(msg)
        if urlsplit(server.endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}:
            msg = "documentation writes are restricted to loopback"
            raise ValueError(msg)
        if "_authoring" not in self._seen:
            session = self._stack.enter_context(
                httpx.Client(
                    headers={
                        "Authorization": f"Bearer {server.access_jwt}",
                    }
                )
            )
            self._bindings["session"] = session
            self._seen.add("_authoring")
        return {
            "pds_endpoint": server.endpoint,
            "repo_did": server.did,
            "session": self._bindings["session"],
        }

    def _conllu(self) -> None:
        """Seed a complete projected UD snapshot with a development split."""
        repository = Repository.init(Path(self.config.work_dir) / "ud-store")
        projector = Projector(corpus_ref=str(self._bindings["corpus_uri"]), split="dev")
        repository.save_many_raw(
            (record.uri, record.value())
            for record in projector.project(parse(_DOC_CONLLU))
        )
        repository.commit("seed UD documentation example")

    def _hub(self) -> None:
        """Record the network boundary while retaining real Arrow export behavior."""
        import datasets  # noqa: PLC0415
        import huggingface_hub  # noqa: PLC0415

        table = self._bindings["table"]
        if not isinstance(table, pa.Table):
            msg = "documentation exporter fixture needs an Arrow table"
            raise TypeError(msg)
        mirrored = datasets.Dataset(table)
        self._stack.enter_context(
            patch.object(datasets.Dataset, "push_to_hub", return_value=None)
        )
        self._stack.enter_context(
            patch.object(huggingface_hub.HfApi, "upload_file", return_value=None)
        )
        self._stack.enter_context(
            patch.object(datasets, "load_dataset", return_value=mirrored)
        )

    def _knowledge(self) -> None:
        """Keep lexical search data and cross-reference behavior fully local."""
        root = Path(self.config.work_dir) / "glazing"
        converted = root / "converted"
        converted.mkdir(parents=True)
        self._stack.enter_context(
            patch.dict(os.environ, {"GLAZING_DATA_DIR": str(root)})
        )
        self._stack.enter_context(
            patch.object(GlazingKB, "_index", _documentation_xrefs)
        )
        if importlib.util.find_spec("glazing") is not None:
            from glazing.propbank.models import Frameset, Roleset  # noqa: PLC0415
            from glazing.wordnet.models import Synset, Word  # noqa: PLC0415

            frameset = Frameset(
                predicate_lemma="give",
                rolesets=[Roleset(id="give.01", name="give", roles=[])],
            )
            (converted / "propbank.jsonl").write_text(frameset.model_dump_json() + "\n")
            synset = Synset(
                offset="00001740",
                lex_filenum=0,
                lex_filename="verb.possession",
                ss_type="v",
                words=[Word(lemma="give", lex_id=0)],
                gloss="transfer possession",
            )
            (converted / "wordnet.jsonl").write_text(synset.model_dump_json() + "\n")

    def _media(self, profile: str) -> dict[str, DocumentationValue]:
        """Return separate correctly encoded handles for each modality."""
        if profile == "video":
            import av  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415

            buffer = io.BytesIO()
            with av.open(buffer, mode="w", format="mp4") as output:
                stream = output.add_stream("mpeg4", rate=1)
                stream.width = stream.height = 16
                stream.pix_fmt = "yuv420p"
                for index in range(5):
                    frame = av.VideoFrame.from_ndarray(
                        np.full((16, 16, 3), index * 40, dtype=np.uint8), format="rgb24"
                    )
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)
            handle = MediaHandle(
                cid=self._cid,
                mime_type="video/mp4",
                modality="video",
                data=buffer.getvalue(),
            )
            return {"handle": handle}
        if profile == "neural":
            import mne  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415

            info = mne.create_info(ch_names=["Cz", "Pz"], sfreq=100.0, ch_types="eeg")
            raw = mne.io.RawArray(np.zeros((2, 101)), info, verbose=False)
            path = Path(self.config.work_dir) / "sample_raw.fif"
            raw.save(path, overwrite=True, verbose=False)
            handle = MediaHandle(
                cid=self._cid,
                mime_type="application/x-fif",
                modality="audio",
                data=path.read_bytes(),
            )
            return {"handle": handle}
        handle = MediaHandle(
            cid=self._cid, mime_type="audio/wav", modality="audio", data=self._audio
        )
        media_record = Media(
            kind="audio",
            createdAt=datetime(2026, 1, 1, tzinfo=UTC),
            mimeType="audio/wav",
            blob=BlobRef(cid=self._cid, mime_type="audio/wav", size=len(self._audio)),
        )
        return {
            "handle": handle,
            "media_record": media_record,
            "pds_endpoint": _DOC_PDS,
        }

    def _route(self, request: httpx.Request) -> httpx.Response:
        """Return fixed responses for declared read services; reject all others."""
        host = request.url.host
        if host in {"www.wikidata.org", "query.wikidata.org", "wikidata.reconci.link"}:
            return self._knowledge_response(request)
        if host == "media.example":
            return httpx.Response(
                200, content=self._audio, headers={"Content-Type": "audio/wav"}
            )
        allowed = {
            "pds.example",
            "repo.layers.pub",
            "plc.directory",
            "alice.bsky.social",
            "appview.example",
        }
        if host not in allowed:
            msg = (
                "unexpected external request in documentation: "
                f"{request.method} {request.url}"
            )
            raise RuntimeError(msg)
        did = (
            request.url.params.get("repo") or request.url.params.get("did") or self._did
        )
        records = self._repo_records(did)
        if host == "alice.bsky.social":
            return httpx.Response(200, text=self._did)
        if host == "plc.directory":
            return httpx.Response(
                200,
                json={
                    "id": did,
                    "service": [
                        {
                            "id": "#atproto_pds",
                            "type": "AtprotoPersonalDataServer",
                            "serviceEndpoint": _DOC_PDS,
                        }
                    ],
                },
            )
        return self._pds_response(request, did, records)

    def _pds_response(
        self, request: httpx.Request, did: str, records: tuple[RecordEnvelope, ...]
    ) -> httpx.Response:
        """Return fixture responses for the PDS and appview XRPC methods."""
        path = request.url.path
        if path.endswith("getBlob"):
            return httpx.Response(
                200, content=self._audio, headers={"Content-Type": "audio/wav"}
            )
        if path.endswith("getRepo"):
            return httpx.Response(
                200,
                content=_documentation_car(did, records),
                headers={"Content-Type": "application/vnd.ipld.car"},
            )
        if path.endswith("getRecord"):
            collection = request.url.params["collection"]
            rkey = request.url.params["rkey"]
            selected = next(
                (
                    record
                    for record in records
                    if record.uri.endswith(f"/{collection}/{rkey}")
                ),
                records[0],
            )
            return httpx.Response(
                200,
                json={
                    "uri": f"at://{did}/{collection}/{rkey}",
                    "cid": selected.cid,
                    "value": selected.value,
                },
            )
        if path.endswith("listRecords"):
            collection = request.url.params["collection"]
            selected = [
                record.model_dump()
                for record in records
                if f"/{collection}/" in record.uri
            ]
            return httpx.Response(200, json={"records": selected})
        if path.endswith("describeRepo"):
            return httpx.Response(
                200,
                json={
                    "did": did,
                    "handle": "alice.bsky.social",
                    "handleIsCorrect": True,
                    "didDoc": {},
                    "collections": sorted(
                        {record.uri.split("/")[3] for record in records}
                    ),
                },
            )
        if request.url.host == "appview.example":
            corpus = records[2].model_dump()
            return httpx.Response(
                200, json={"records": [corpus]} if ".list" in path else corpus
            )
        msg = f"unexpected fixture PDS request: {request.url}"
        raise RuntimeError(msg)

    def _knowledge_response(self, request: httpx.Request) -> httpx.Response:
        """Serve the entity, search, SPARQL, and reconciliation fixture shapes."""
        if request.url.path == "/wiki/Special:EntityData/Q42.json":
            return httpx.Response(307, headers={"Location": "/recorded/Q42.json"})
        if request.url.host == "wikidata.reconci.link":
            return self._reconciliation_response(request)
        if request.url.host == "query.wikidata.org":
            return httpx.Response(
                200,
                json={
                    "results": {
                        "bindings": [
                            {
                                "p": {
                                    "value": "http://www.wikidata.org/prop/direct/P31"
                                },
                                "o": {"value": "http://www.wikidata.org/entity/Q5"},
                            }
                        ]
                    }
                },
            )
        if request.url.path.endswith("/api.php"):
            return httpx.Response(
                200, json={"search": [{"id": "Q42", "label": "Douglas Adams"}]}
            )
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q42": {
                        "labels": {"en": {"value": "Douglas Adams"}},
                        "claims": {
                            "P31": [
                                {"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}
                            ]
                        },
                    }
                }
            },
        )

    def _reconciliation_response(self, request: httpx.Request) -> httpx.Response:
        """Return fixed reconciliation manifest, query, and extension results."""
        if request.method == "GET":
            if request.url.path.endswith("/suggest/entity"):
                return httpx.Response(
                    200, json={"result": [{"id": "Q7259", "name": "Ada Lovelace"}]}
                )
            return httpx.Response(
                200,
                json={
                    "name": "Recorded reconciliation",
                    "extend": {"propose_properties": {"properties": [{"id": "P25"}]}},
                    "suggest": {
                        "entity": {
                            "service_url": "https://wikidata.reconci.link",
                            "service_path": "/suggest/entity",
                        }
                    },
                },
            )
        payload = json.loads(request.content)
        if "queries" in payload:
            return httpx.Response(
                200,
                json={
                    "q0": {
                        "result": [
                            {
                                "id": "Q7259",
                                "name": "Ada Lovelace",
                                "score": 100,
                                "type": [{"id": "Q5", "name": "human"}],
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "rows": {"Q7259": {"P25": [{"id": "Q43845", "name": "Anne Isabella"}]}}
            },
        )


@contextlib.contextmanager
def documentation_runtime(
    config: DocumentationConfig,
) -> Iterator[DocumentationRuntime]:
    """Yield an isolated example runtime and restore its boundaries.

    Parameters
    ----------
    config : DocumentationConfig
        Disposable paths and optional local-PDS connection details.

    Yields
    ------
    DocumentationRuntime
        The active fixture context for one example subprocess.
    """
    with DocumentationRuntime(config) as runtime:
        yield runtime


@pytest.fixture
def documentation_runtime_factory() -> Callable[
    [DocumentationConfig], AbstractContextManager[DocumentationRuntime]
]:
    """Expose the runtime to tests without importing an importlib conftest.

    Returns
    -------
    collections.abc.Callable
        The documentation context-manager factory.
    """
    return documentation_runtime
