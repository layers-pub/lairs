"""Unit and integration tests for lairs.atproto.auth."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto import auth
from lairs.atproto.auth import (
    Session,
    SessionAuth,
    SessionStore,
    authed_client,
    login,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import PdsServer

_ENDPOINT = "https://pds.example"
_GET = f"{_ENDPOINT}/xrpc/com.atproto.repo.getRecord"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exports() -> None:
    assert set(auth.__all__) == {
        "Session",
        "SessionAuth",
        "SessionStore",
        "authed_client",
        "login",
    }


def test_login_creates_session() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.server.createSession"
        return httpx.Response(
            200,
            json={
                "did": "did:plc:x",
                "handle": "alice.test",
                "accessJwt": "access",
                "refreshJwt": "refresh",
            },
        )

    session = login("alice.test", "app-pw", pds=_ENDPOINT, client=_client(handler))
    assert session.did == "did:plc:x"
    assert session.handle == "alice.test"
    assert session.access_jwt == "access"
    assert session.refresh_jwt == "refresh"
    assert session.pds_endpoint == _ENDPOINT
    assert session.password == "app-pw"  # retained for re-auth


def test_login_raises_on_bad_credentials() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        login(
            "alice.test",
            "wrong",
            pds=_ENDPOINT,
            client=_client(lambda _r: httpx.Response(401)),
        )


def test_session_auth_attaches_bearer() -> None:
    session = Session(
        did="did:plc:x",
        pds_endpoint=_ENDPOINT,
        access_jwt="access",
        refresh_jwt="refresh",
    )
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={})

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        auth=SessionAuth(session),
    ) as client:
        client.get(_GET)
    assert seen["auth"] == "Bearer access"


def test_session_auth_refreshes_on_401() -> None:
    session = Session(
        did="did:plc:x",
        pds_endpoint=_ENDPOINT,
        access_jwt="old-access",
        refresh_jwt="old-refresh",
    )
    updates: list[Session] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("refreshSession"):
            assert request.headers["Authorization"] == "Bearer old-refresh"
            return httpx.Response(
                200,
                json={"accessJwt": "new-access", "refreshJwt": "new-refresh"},
            )
        if request.headers.get("Authorization") == "Bearer old-access":
            return httpx.Response(401, json={"error": "ExpiredToken"})
        assert request.headers["Authorization"] == "Bearer new-access"
        return httpx.Response(200, json={"ok": True})

    auth_flow = SessionAuth(session, on_update=updates.append)
    with httpx.Client(transport=httpx.MockTransport(handler), auth=auth_flow) as client:
        response = client.get(_GET)
    assert response.status_code == 200
    assert auth_flow.session.access_jwt == "new-access"
    assert auth_flow.session.refresh_jwt == "new-refresh"
    assert updates[-1].access_jwt == "new-access"


def test_session_auth_relogins_when_refresh_dead() -> None:
    session = Session(
        did="did:plc:x",
        pds_endpoint=_ENDPOINT,
        access_jwt="old",
        refresh_jwt="dead",
        password="app-pw",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("refreshSession"):
            return httpx.Response(400, json={"error": "ExpiredToken"})
        if request.url.path.endswith("createSession"):
            assert request.headers.get("Authorization") is None
            return httpx.Response(
                200,
                json={"accessJwt": "fresh", "refreshJwt": "fresh-refresh"},
            )
        if request.headers.get("Authorization") == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={})

    auth_flow = SessionAuth(session)
    with httpx.Client(transport=httpx.MockTransport(handler), auth=auth_flow) as client:
        response = client.get(_GET)
    assert response.status_code == 200
    assert auth_flow.session.access_jwt == "fresh"


def test_session_auth_gives_up_without_password() -> None:
    session = Session(
        did="did:plc:x",
        pds_endpoint=_ENDPOINT,
        access_jwt="old",
        refresh_jwt="dead",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("refreshSession"):
            return httpx.Response(400)
        return httpx.Response(401, json={"error": "ExpiredToken"})

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        auth=SessionAuth(session),
    ) as client:
        response = client.get(_GET)
    # renewal failed and no password to re-login: the endpoint's 401 stands.
    assert response.status_code == 401


def test_session_store_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "auth.json")
    assert store.load() is None
    session = Session(
        did="did:plc:x",
        pds_endpoint=_ENDPOINT,
        access_jwt="a",
        refresh_jwt="r",
        handle="alice.test",
        password="app-pw",
    )
    store.save(session)
    assert store.load() == session
    assert (store.path.stat().st_mode & 0o777) == 0o600
    assert store.delete() is True
    assert store.load() is None
    assert store.delete() is False


def test_default_session_path_honors_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAIRS_AUTH_FILE", "/tmp/lairs-test/session.json")  # noqa: S108
    assert str(SessionStore().path) == "/tmp/lairs-test/session.json"  # noqa: S108


def test_default_session_path_uses_xdg_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAIRS_AUTH_FILE", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/xdg-state")  # noqa: S108
    path = SessionStore().path
    assert str(path) == "/tmp/xdg-state/lairs/auth-session.json"  # noqa: S108


def test_session_auth_persists_refresh_via_store(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "auth.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("refreshSession"):
            return httpx.Response(
                200,
                json={"accessJwt": "new-access", "refreshJwt": "new-refresh"},
            )
        if request.headers.get("Authorization") == "Bearer old-access":
            return httpx.Response(401)
        return httpx.Response(200, json={})

    session = Session(
        did="did:plc:x",
        pds_endpoint=_ENDPOINT,
        access_jwt="old-access",
        refresh_jwt="old-refresh",
    )
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        auth=SessionAuth(session, on_update=store.save),
    ) as client:
        client.get(_GET)
    persisted = store.load()
    assert persisted is not None
    assert persisted.access_jwt == "new-access"


def test_authed_client_builds_a_client() -> None:
    session = Session(
        did="did:plc:x",
        pds_endpoint=_ENDPOINT,
        access_jwt="a",
        refresh_jwt="r",
    )
    with authed_client(session) as client:
        assert isinstance(client, httpx.Client)


def _create_app_password(server: PdsServer) -> str:
    """Mint an app password for the live account via the admin-less user API."""
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.server.createAppPassword",
        headers={"Authorization": f"Bearer {server.access_jwt}"},
        json={"name": "lairs-test"},
        timeout=30.0,
    )
    response.raise_for_status()
    return str(response.json()["password"])


@pytest.mark.integration
def test_login_and_authed_client_live(pds_server: PdsServer) -> None:
    # log in with an app password, then use the self-renewing client to make an
    # authenticated write against the real PDS.
    app_password = _create_app_password(pds_server)
    session = login(pds_server.handle, app_password, pds=pds_server.endpoint)
    assert session.did == pds_server.did
    with authed_client(session) as client:
        created = client.post(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": pds_server.did,
                "collection": "pub.layers.expression.expression",
                "record": {
                    "$type": "pub.layers.expression.expression",
                    "id": "00000000-0000-0000-0000-000000000000",
                    "text": "authed write",
                    "kind": "sentence",
                    "createdAt": "2026-06-18T00:00:00Z",
                },
            },
        )
    assert created.status_code == 200
