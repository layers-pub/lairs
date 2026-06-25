"""Unit and integration tests for lairs.atproto.identity."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto import identity
from lairs.atproto.identity import IdentityError, IdentityResolution, IdentityResolver

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from conftest import PdsServer, RouteHandler

    from lairs._types import JsonValue

_DID = "did:plc:abc123"
_HANDLE = "alice.test"
_PDS = "https://pds.example"

_PLC_DOCUMENT: JsonValue = {
    "id": _DID,
    "service": [
        {
            "id": "#atproto_pds",
            "type": "AtprotoPersonalDataServer",
            "serviceEndpoint": _PDS,
        },
    ],
}


def _resolver(
    handler: Callable[[httpx.Request], httpx.Response],
) -> IdentityResolver:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return IdentityResolver(client)


def test_exports() -> None:
    assert set(identity.__all__) == {
        "IdentityError",
        "IdentityResolution",
        "IdentityResolver",
        "resolve_did",
        "resolve_handle",
        "resolve_pds",
    }


def test_resolve_handle_via_well_known() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/atproto-did"
        return httpx.Response(200, text=f"{_DID}\n")

    with _resolver(handler) as resolver:
        assert resolver.resolve_handle(_HANDLE) == _DID


def test_resolve_handle_caches_result() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=_DID)

    with _resolver(handler) as resolver:
        assert resolver.resolve_handle(_HANDLE) == _DID
        assert resolver.resolve_handle(_HANDLE) == _DID
    assert calls["n"] == 1


def test_resolve_handle_failure_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with _resolver(handler) as resolver, pytest.raises(IdentityError):
        resolver.resolve_handle(_HANDLE)


def test_resolve_handle_rejects_non_did_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-a-did")

    with _resolver(handler) as resolver, pytest.raises(IdentityError):
        resolver.resolve_handle(_HANDLE)


def test_resolve_did_plc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/{_DID}"
        return httpx.Response(200, json=_PLC_DOCUMENT)

    with _resolver(handler) as resolver:
        document = resolver.resolve_did(_DID)
    assert document["id"] == _DID


def test_resolve_did_caches_document() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_PLC_DOCUMENT)

    with _resolver(handler) as resolver:
        resolver.resolve_did(_DID)
        resolver.resolve_did(_DID)
    assert calls["n"] == 1


def test_resolve_did_web_uses_well_known() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        assert request.url.path == "/.well-known/did.json"
        return httpx.Response(200, json={"id": "did:web:example.com", "service": []})

    with _resolver(handler) as resolver:
        document = resolver.resolve_did("did:web:example.com")
    assert document["id"] == "did:web:example.com"


def test_resolve_did_web_with_path_segments() -> None:
    # did:web with path segments resolves to /<path>/did.json under the host,
    # exercising the multi-part branch of _did_web_to_url.
    did = "did:web:example.com:user:alice"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        assert request.url.path == "/user/alice/did.json"
        return httpx.Response(200, json={"id": did, "service": []})

    with _resolver(handler) as resolver:
        document = resolver.resolve_did(did)
    assert document["id"] == did


def test_resolve_did_web_with_percent_encoded_port() -> None:
    # a percent-encoded port colon in the host segment is decoded back to ':',
    # so the document is fetched from the explicit host:port with its path.
    did = "did:web:localhost%3A8443:user:alice"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "localhost"
        assert request.url.port == 8443
        assert request.url.path == "/user/alice/did.json"
        return httpx.Response(200, json={"id": did, "service": []})

    with _resolver(handler) as resolver:
        document = resolver.resolve_did(did)
    assert document["id"] == did


def test_resolve_did_rejects_unknown_method() -> None:
    with (
        _resolver(lambda _r: httpx.Response(200)) as resolver,
        pytest.raises(IdentityError),
    ):
        resolver.resolve_did("did:example:nope")


def test_resolve_pds_extracts_endpoint() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_PLC_DOCUMENT)

    with _resolver(handler) as resolver:
        assert resolver.resolve_pds(_DID) == _PDS


def test_resolve_pds_missing_service_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": _DID, "service": []})

    with _resolver(handler) as resolver, pytest.raises(IdentityError):
        resolver.resolve_pds(_DID)


def test_resolve_full_from_handle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/atproto-did":
            return httpx.Response(200, text=_DID)
        return httpx.Response(200, json=_PLC_DOCUMENT)

    with _resolver(handler) as resolver:
        resolution = resolver.resolve(_HANDLE)
    assert isinstance(resolution, IdentityResolution)
    assert resolution.did == _DID
    assert resolution.pds_endpoint == _PDS
    assert resolution.handle == _HANDLE


def test_resolve_full_from_did_has_no_handle() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_PLC_DOCUMENT)

    with _resolver(handler) as resolver:
        resolution = resolver.resolve(_DID)
    assert resolution.did == _DID
    assert resolution.handle is None


def _plc_routes(path: str, _params: dict[str, str]) -> tuple[int, JsonValue]:
    """Serve the PLC directory contract: GET /{did} returns the document."""
    if path == f"/{_DID}":
        return 200, _PLC_DOCUMENT
    return 404, {"message": "did not registered"}


@pytest.mark.integration
def test_resolve_against_local_plc_server(
    route_server: Callable[[RouteHandler], AbstractContextManager[str]],
) -> None:
    # resolve a did to its document and pds through a loopback PLC directory,
    # over the real httpx transport rather than a mock.
    with route_server(_plc_routes) as plc, httpx.Client() as client:
        resolver = IdentityResolver(client, plc_directory=plc)
        document = resolver.resolve_did(_DID)
        assert document["id"] == _DID
        assert resolver.resolve_pds(_DID) == _PDS
        resolution = resolver.resolve(_DID)
    assert resolution.did == _DID
    assert resolution.pds_endpoint == _PDS
    assert resolution.handle is None


@pytest.mark.integration
def test_resolve_against_real_did_document_live(
    pds_server: PdsServer,
    route_server: Callable[[RouteHandler], AbstractContextManager[str]],
) -> None:
    # serve the real did document the dev PDS published from a loopback PLC,
    # then resolve the full chain through it; proves the resolver parses a real
    # atproto did document and recovers the PDS endpoint it advertises.
    described = httpx.get(
        f"{pds_server.endpoint}/xrpc/com.atproto.repo.describeRepo",
        params={"repo": pds_server.did},
        timeout=30.0,
    )
    described.raise_for_status()
    did_document = described.json()["didDoc"]

    def routes(path: str, _params: dict[str, str]) -> tuple[int, JsonValue]:
        if path == f"/{pds_server.did}":
            return 200, did_document
        return 404, {"message": "unknown did"}

    with route_server(routes) as plc, httpx.Client() as client:
        resolver = IdentityResolver(client, plc_directory=plc)
        resolution = resolver.resolve(pds_server.did)
    assert resolution.did == pds_server.did
    assert resolution.handle is None
    assert resolution.pds_endpoint == pds_server.endpoint
