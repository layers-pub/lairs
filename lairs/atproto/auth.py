"""App-password authentication and session management for PDS accounts.

lairs authenticates writes (and private reads) with an ATProto app-password
session: ``login`` resolves an actor to its PDS and calls
``com.atproto.server.createSession``; ``SessionAuth`` is an ``httpx.Auth`` that
attaches the access token and, on a 401, refreshes via
``com.atproto.server.refreshSession`` (falling back to a fresh login with the
stored app password when the refresh token has also expired); and
``SessionStore`` persists the session to the XDG state directory so a single
``login`` carries across commands. This mirrors the ergonomics of ``goat``.

The persisted session file contains credentials (the access and refresh tokens
and the app password used for seamless re-auth); it is written with ``0600``
permissions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx
import httpx

from lairs.atproto.identity import IdentityResolver

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from lairs._types import JsonValue

__all__ = [
    "Session",
    "SessionAuth",
    "SessionRenewalError",
    "SessionStore",
    "authed_client",
    "login",
]

_CREATE_SESSION_NSID = "com.atproto.server.createSession"
"""The XRPC procedure that exchanges an app password for a session."""

_REFRESH_SESSION_NSID = "com.atproto.server.refreshSession"
"""The XRPC procedure that rotates a session's tokens."""

_AUTH_FILE_ENV = "LAIRS_AUTH_FILE"
"""The environment variable that overrides the session file location."""

_XDG_STATE_ENV = "XDG_STATE_HOME"
"""The environment variable for the XDG state base directory."""

_SESSION_FILE = "auth-session.json"
"""The session file name within the lairs state directory."""

_FILE_MODE = 0o600
"""The permission bits for the credential-bearing session file."""


class Session(dx.Model):
    """An authenticated PDS session.

    Attributes
    ----------
    did : str
        The authenticated account DID.
    pds_endpoint : str
        The base URL of the account's PDS.
    access_jwt : str
        The short-lived access token.
    refresh_jwt : str
        The long-lived refresh token.
    handle : str or None
        The account handle, when known.
    password : str or None
        The app password, retained to re-authenticate when the refresh token
        expires. ``None`` for an in-memory session that should not re-login.
    """

    did: str = dx.field(description="authenticated account DID")
    pds_endpoint: str = dx.field(description="base URL of the account's PDS")
    access_jwt: str = dx.field(description="short-lived access token")
    refresh_jwt: str = dx.field(description="long-lived refresh token")
    handle: str | None = dx.field(default=None, description="account handle")
    password: str | None = dx.field(
        default=None,
        description="app password retained for re-authentication",
    )


class SessionRenewalError(httpx.HTTPError):
    """Raised when a 401 cannot be recovered by renewing the session.

    This is raised by ``SessionAuth`` when the access token is rejected and
    neither ``refreshSession`` nor a stored-password ``createSession`` login
    can mint a fresh token. It subclasses ``httpx.HTTPError`` so a caller that
    already catches transport errors catches it too. Raising rather than
    re-sending the original request means a non-idempotent write whose renewal
    fails is attempted against the target endpoint exactly once.
    """


def _xrpc(endpoint: str, nsid: str) -> str:
    """Build the XRPC URL for a procedure NSID on a PDS."""
    return f"{endpoint.rstrip('/')}/xrpc/{nsid}"


def _resolve_pds(identifier: str, resolver: IdentityResolver | None) -> str:
    """Resolve an actor identifier to its PDS endpoint."""
    if resolver is not None:
        return resolver.resolve(identifier).pds_endpoint
    with IdentityResolver() as active:
        return active.resolve(identifier).pds_endpoint


def login(
    identifier: str,
    app_password: str,
    *,
    pds: str | None = None,
    resolver: IdentityResolver | None = None,
    client: httpx.Client | None = None,
) -> Session:
    """Authenticate with an app password and return a session.

    Resolves ``identifier`` (a handle or DID) to its PDS unless ``pds`` is given,
    then calls ``com.atproto.server.createSession``. The returned session retains
    the app password so a stored session can re-authenticate after its refresh
    token expires.

    Parameters
    ----------
    identifier : str
        The account handle or DID.
    app_password : str
        An app password (not the account password).
    pds : str or None, optional
        The PDS base URL; skips identity resolution when given.
    resolver : IdentityResolver or None, optional
        An injected identity resolver for the resolution step.
    client : httpx.Client or None, optional
        An injected HTTP client; a private one is created when omitted.

    Returns
    -------
    Session
        The authenticated session.

    Raises
    ------
    httpx.HTTPStatusError
        If the PDS rejects the credentials.
    """
    owns_client = client is None
    http = client if client is not None else httpx.Client()
    try:
        endpoint = pds if pds is not None else _resolve_pds(identifier, resolver)
        response = http.post(
            _xrpc(endpoint, _CREATE_SESSION_NSID),
            json={"identifier": identifier, "password": app_password},
        )
        response.raise_for_status()
        body = response.json()
    finally:
        if owns_client:
            http.close()
    fields = body if isinstance(body, dict) else {}
    handle = fields.get("handle")
    return Session(
        did=str(fields.get("did", "")),
        pds_endpoint=endpoint,
        access_jwt=str(fields.get("accessJwt", "")),
        refresh_jwt=str(fields.get("refreshJwt", "")),
        handle=handle if isinstance(handle, str) else None,
        password=app_password,
    )


class SessionAuth(httpx.Auth):
    """An ``httpx.Auth`` that attaches and self-renews a PDS access token.

    Each request carries the session's access token. On a 401 the access token
    is refreshed through ``refreshSession``; if that also fails and the session
    retains an app password, a fresh ``createSession`` login is attempted. When
    the tokens rotate, an optional callback is invoked so a store can persist
    them.

    Parameters
    ----------
    session : Session
        The session whose tokens to attach and renew.
    on_update : collections.abc.Callable or None, optional
        A callback invoked with the new session whenever the tokens rotate.
    """

    requires_response_body = True

    def __init__(
        self,
        session: Session,
        *,
        on_update: Callable[[Session], None] | None = None,
    ) -> None:
        self.session = session
        self._on_update = on_update

    def auth_flow(
        self,
        request: httpx.Request,
    ) -> Generator[httpx.Request, httpx.Response]:
        """Attach the access token, renewing it once on a 401.

        The original request is retried only when renewal actually rotated the
        access token, so the response the caller receives is the target
        endpoint's and not an intermediate refresh response. When renewal does
        not yield a new token (a dead refresh token and no stored password) the
        request is not re-sent with the unchanged stale token; instead a
        ``SessionRenewalError`` is raised. This means a non-idempotent write
        whose renewal fails is attempted against the target endpoint exactly
        once rather than twice.

        Raises
        ------
        SessionRenewalError
            If the access token is rejected and renewal mints no new token.
        """
        request.headers["Authorization"] = f"Bearer {self.session.access_jwt}"
        response = yield request
        if response.status_code != httpx.codes.UNAUTHORIZED:
            return
        previous_token = self.session.access_jwt
        yield from self._renew()
        if self.session.access_jwt == previous_token:
            msg = (
                f"session renewal failed for {self.session.did}: "
                "the access token was rejected and no fresh token could be minted"
            )
            raise SessionRenewalError(msg)
        request.headers["Authorization"] = f"Bearer {self.session.access_jwt}"
        yield request

    def _renew(self) -> Generator[httpx.Request, httpx.Response]:
        """Rotate tokens via refreshSession, then a password login if needed."""
        refresh = httpx.Request(
            "POST",
            _xrpc(self.session.pds_endpoint, _REFRESH_SESSION_NSID),
            headers={"Authorization": f"Bearer {self.session.refresh_jwt}"},
        )
        refreshed = yield refresh
        if refreshed.status_code == httpx.codes.OK:
            self._apply(refreshed.json())
            return
        if self.session.password is None:
            return
        relogin = httpx.Request(
            "POST",
            _xrpc(self.session.pds_endpoint, _CREATE_SESSION_NSID),
            json={"identifier": self.session.did, "password": self.session.password},
        )
        reissued = yield relogin
        if reissued.status_code == httpx.codes.OK:
            self._apply(reissued.json())

    def _apply(self, body: JsonValue) -> None:
        """Replace the session with rotated tokens and notify the callback."""
        if not isinstance(body, dict):
            return
        did = body.get("did")
        handle = body.get("handle")
        self.session = Session(
            did=did if isinstance(did, str) else self.session.did,
            pds_endpoint=self.session.pds_endpoint,
            access_jwt=str(body.get("accessJwt", self.session.access_jwt)),
            refresh_jwt=str(body.get("refreshJwt", self.session.refresh_jwt)),
            handle=handle if isinstance(handle, str) else self.session.handle,
            password=self.session.password,
        )
        if self._on_update is not None:
            self._on_update(self.session)


def _default_session_path() -> Path:
    """Return the session file path, honoring the override and XDG state dir."""
    override = os.environ.get(_AUTH_FILE_ENV)
    if override:
        return Path(override)
    state_home = os.environ.get(_XDG_STATE_ENV)
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "lairs" / _SESSION_FILE


class SessionStore:
    """A file-backed store for the authenticated session.

    The session is written to the XDG state directory (or the path given by the
    ``LAIRS_AUTH_FILE`` environment variable) with ``0600`` permissions, since it
    holds credentials.

    Parameters
    ----------
    path : pathlib.Path or None, optional
        An explicit session file path; the default location is used when
        omitted.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else _default_session_path()

    @property
    def path(self) -> Path:
        """Return the session file path.

        Returns
        -------
        pathlib.Path
            The session file path.
        """
        return self._path

    def save(self, session: Session) -> None:
        """Persist a session, creating the file with restricted permissions.

        Parameters
        ----------
        session : Session
            The session to persist.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self._path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            _FILE_MODE,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(session.model_dump_json())
        self._path.chmod(_FILE_MODE)

    def load(self) -> Session | None:
        """Load the stored session, or ``None`` when none is stored.

        Returns
        -------
        Session or None
            The stored session, or ``None``.
        """
        if not self._path.exists():
            return None
        return Session.model_validate_json(self._path.read_text(encoding="utf-8"))

    def delete(self) -> bool:
        """Delete the stored session.

        Returns
        -------
        bool
            ``True`` if a session file was present and removed.
        """
        existed = self._path.exists()
        self._path.unlink(missing_ok=True)
        return existed


def authed_client(
    session: Session, *, store: SessionStore | None = None
) -> httpx.Client:
    """Build an HTTP client that authenticates and self-renews a session.

    Parameters
    ----------
    session : Session
        The session to authenticate with.
    store : SessionStore or None, optional
        A store to persist rotated tokens to; refreshes are kept in memory only
        when omitted.

    Returns
    -------
    httpx.Client
        A client whose requests carry and renew the session's tokens.
    """
    on_update = store.save if store is not None else None
    return httpx.Client(auth=SessionAuth(session, on_update=on_update))
