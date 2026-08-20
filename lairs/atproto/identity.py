"""Identity resolution: handle to DID and DID to PDS endpoint.

Resolves a handle to a DID (via DNS TXT or the ``.well-known/atproto-did``
HTTP endpoint), a DID to its DID document (via the PLC directory for
``did:plc`` or the ``did:web`` document), and a DID to its PDS service
endpoint. Resolutions are cached in memory so repeated lookups during a pull do
not re-hit the network.

The transport is built on ``httpx`` rather than the ``atproto`` SDK. Public
reads need no auth; an injected client can later carry a session for private
reads. All results are returned as ``dx.Model`` instances.
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING, Self

import didactic.api as dx
import dns.exception
import dns.resolver
import httpx

if TYPE_CHECKING:
    from types import TracebackType

    from lairs._types import JsonValue

__all__ = [
    "IdentityError",
    "IdentityResolution",
    "IdentityResolver",
    "resolve_did",
    "resolve_handle",
    "resolve_pds",
]

DEFAULT_PLC_DIRECTORY = "https://plc.directory"
"""The default PLC directory used to resolve ``did:plc`` identifiers."""

_ATPROTO_PDS_SERVICE_ID = "#atproto_pds"
"""The DID document service identifier for an ATProto PDS endpoint."""

_ATPROTO_PDS_SERVICE_TYPE = "AtprotoPersonalDataServer"
"""The DID document service type for an ATProto PDS endpoint."""

_DNS_TIMEOUT_SECONDS = 5.0
"""The per-query lifetime for the ``_atproto`` DNS TXT handle lookup."""


class IdentityResolution(dx.Model):
    """The resolved identity of an ATProto repository.

    Attributes
    ----------
    did : str
        The resolved decentralised identifier.
    pds_endpoint : str
        The base URL of the repository's personal data server.
    handle : str or None, optional
        The handle the resolution started from, when known.
    """

    did: str = dx.field(description="resolved decentralised identifier")
    pds_endpoint: str = dx.field(
        description="base URL of the repository's personal data server",
    )
    handle: str | None = dx.field(
        default=None,
        description="handle the resolution started from, when known",
    )


class IdentityError(RuntimeError):
    """Raised when an identity cannot be resolved.

    This wraps DNS, HTTP, and document-shape failures behind a single error so
    callers do not have to discriminate transport-specific exceptions.
    """


def _did_web_to_url(did: str) -> str:
    """Build the document URL for a ``did:web`` identifier.

    Parameters
    ----------
    did : str
        A ``did:web`` identifier.

    Returns
    -------
    str
        The ``https`` URL of the DID document.

    Raises
    ------
    IdentityError
        If the identifier is not a ``did:web`` identifier.
    """
    prefix = "did:web:"
    if not did.startswith(prefix):
        msg = f"not a did:web identifier: {did}"
        raise IdentityError(msg)
    # did:web encodes the host (and optional path) after the method, with
    # colons separating path segments and percent-encoded port colons.
    suffix = did.removeprefix(prefix)
    parts = suffix.split(":")
    host = parts[0].replace("%3A", ":")
    if len(parts) == 1:
        return f"https://{host}/.well-known/did.json"
    path = "/".join(parts[1:])
    return f"https://{host}/{path}/did.json"


def _pds_from_document(document: dict[str, JsonValue]) -> str:
    """Extract the PDS service endpoint from a DID document.

    Parameters
    ----------
    document : dict
        A parsed DID document.

    Returns
    -------
    str
        The PDS service endpoint URL.

    Raises
    ------
    IdentityError
        If the document carries no ATProto PDS service entry.
    """
    services = document.get("service")
    if not isinstance(services, list):
        msg = "did document has no service array"
        raise IdentityError(msg)
    for service in services:
        if not isinstance(service, dict):
            continue
        service_id = service.get("id")
        service_type = service.get("type")
        endpoint = service.get("serviceEndpoint")
        identifies_pds = service_id in {_ATPROTO_PDS_SERVICE_ID, "atproto_pds"}
        if (
            identifies_pds
            and service_type == _ATPROTO_PDS_SERVICE_TYPE
            and isinstance(endpoint, str)
        ):
            return endpoint
    msg = "did document has no atproto pds service endpoint"
    raise IdentityError(msg)


class IdentityResolver:
    """A caching resolver for handles, DIDs, and PDS endpoints.

    Parameters
    ----------
    client : httpx.Client or None, optional
        An injected HTTP client. When omitted, a private client is created and
        closed with the resolver. Injecting a client lets a session carry auth
        for private reads later.
    plc_directory : str, optional
        The PLC directory base URL used for ``did:plc`` resolution.
    dns_timeout : float, optional
        The per-query lifetime, in seconds, for the ``_atproto`` DNS TXT lookup.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        plc_directory: str = DEFAULT_PLC_DIRECTORY,
        dns_timeout: float = _DNS_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None
        self._plc_directory = plc_directory.rstrip("/")
        self._dns_timeout = dns_timeout
        self._handle_cache: dict[str, str] = {}
        self._document_cache: dict[str, dict[str, JsonValue]] = {}
        self._pds_cache: dict[str, str] = {}

    def __enter__(self) -> Self:
        """Enter the resolver as a context manager.

        Returns
        -------
        Self
            This resolver.
        """
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Close the resolver on context-manager exit.

        Parameters
        ----------
        _exc_type : type[BaseException] or None
            The exception type, if the block raised.
        _exc : BaseException or None
            The exception instance, if the block raised.
        _tb : types.TracebackType or None
            The traceback, if the block raised.
        """
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client if the resolver owns it."""
        if self._owns_client:
            self._client.close()

    def resolve_handle(self, handle: str) -> str:
        """Resolve a handle to a DID.

        Both ATProto handle-resolution methods are attempted concurrently and
        the first to yield a ``did:`` wins: the DNS ``_atproto`` TXT record and
        the ``.well-known/atproto-did`` HTTP endpoint. Racing them keeps a
        lookup bounded by the faster method, since a handle configures only one
        (a DNS-method handle has no HTTP host; an HTTP-method handle has no TXT
        record). Results are cached.

        Parameters
        ----------
        handle : str
            The ATProto handle (for example ``alice.bsky.social``).

        Returns
        -------
        str
            The resolved DID.

        Raises
        ------
        IdentityError
            If the handle cannot be resolved.
        """
        cached = self._handle_cache.get(handle)
        if cached is not None:
            return cached
        did = self._resolve_handle_concurrent(handle)
        if did is None or not did.startswith("did:"):
            msg = f"could not resolve handle to a did: {handle}"
            raise IdentityError(msg)
        self._handle_cache[handle] = did
        return did

    def _resolve_handle_concurrent(self, handle: str) -> str | None:
        """Race the DNS and HTTP resolution methods; the first DID wins.

        The two methods run at once; the first to return a ``did:`` is used and
        the other is abandoned without blocking the return, so the lookup takes
        as long as the faster method rather than the sum of both.

        Parameters
        ----------
        handle : str
            The ATProto handle.

        Returns
        -------
        str or None
            The resolved DID, or ``None`` if neither method yielded one.
        """
        methods = (self._resolve_handle_dns, self._resolve_handle_http)
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(methods))
        try:
            futures = [pool.submit(method, handle) for method in methods]
            for future in concurrent.futures.as_completed(futures):
                did = future.result()
                if did is not None and did.startswith("did:"):
                    return did
            return None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _resolve_handle_dns(self, handle: str) -> str | None:
        """Resolve a handle via its ``_atproto`` DNS TXT record.

        The record's value is ``did=<did>``. Any DNS failure (no such record,
        timeout, or SERVFAIL) yields ``None`` so the HTTP method can still win.

        Parameters
        ----------
        handle : str
            The ATProto handle.

        Returns
        -------
        str or None
            The DID, or ``None`` if the TXT record did not yield one.
        """
        try:
            answer = dns.resolver.resolve(
                f"_atproto.{handle}",
                "TXT",
                lifetime=self._dns_timeout,
            )
        except dns.exception.DNSException:
            return None
        prefix = "did="
        for record in answer:
            text = b"".join(record.strings).decode("utf-8", "replace").strip()
            if text.startswith(prefix):
                did = text.removeprefix(prefix).strip()
                if did.startswith("did:"):
                    return did
        return None

    def _resolve_handle_http(self, handle: str) -> str | None:
        """Resolve a handle via the ``.well-known/atproto-did`` endpoint.

        Parameters
        ----------
        handle : str
            The ATProto handle.

        Returns
        -------
        str or None
            The DID, or ``None`` if the endpoint did not yield one.
        """
        url = f"https://{handle}/.well-known/atproto-did"
        try:
            response = self._client.get(url, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if response.status_code != httpx.codes.OK:
            return None
        did = response.text.strip()
        return did if did.startswith("did:") else None

    def resolve_did(self, did: str) -> dict[str, JsonValue]:
        """Resolve a DID to its DID document.

        Parameters
        ----------
        did : str
            The DID to resolve (``did:plc`` or ``did:web``).

        Returns
        -------
        dict
            The parsed DID document.

        Raises
        ------
        IdentityError
            If the DID method is unsupported or resolution fails.
        """
        cached = self._document_cache.get(did)
        if cached is not None:
            return cached
        if did.startswith("did:plc:"):
            url = f"{self._plc_directory}/{did}"
        elif did.startswith("did:web:"):
            url = _did_web_to_url(did)
        else:
            msg = f"unsupported did method: {did}"
            raise IdentityError(msg)
        try:
            response = self._client.get(url, follow_redirects=True)
            response.raise_for_status()
            document = response.json()
        except httpx.HTTPError as exc:
            msg = f"could not resolve did document for {did}: {exc}"
            raise IdentityError(msg) from exc
        if not isinstance(document, dict):
            msg = f"did document for {did} was not a json object"
            raise IdentityError(msg)
        self._document_cache[did] = document
        return document

    def resolve_pds(self, did: str) -> str:
        """Resolve a DID to its PDS service endpoint.

        Parameters
        ----------
        did : str
            The DID to resolve.

        Returns
        -------
        str
            The PDS endpoint URL.

        Raises
        ------
        IdentityError
            If the DID document carries no PDS service entry.
        """
        cached = self._pds_cache.get(did)
        if cached is not None:
            return cached
        document = self.resolve_did(did)
        endpoint = _pds_from_document(document)
        self._pds_cache[did] = endpoint
        return endpoint

    def resolve(self, actor: str) -> IdentityResolution:
        """Fully resolve a handle or DID to an identity.

        Parameters
        ----------
        actor : str
            A handle or a DID.

        Returns
        -------
        IdentityResolution
            The resolved identity (did, pds endpoint, and originating handle).
        """
        if actor.startswith("did:"):
            did = actor
            handle: str | None = None
        else:
            did = self.resolve_handle(actor)
            handle = actor
        endpoint = self.resolve_pds(did)
        return IdentityResolution(did=did, pds_endpoint=endpoint, handle=handle)


def resolve_handle(handle: str) -> str:
    """Resolve a handle to a DID using a throwaway resolver.

    Parameters
    ----------
    handle : str
        The ATProto handle (for example ``alice.bsky.social``).

    Returns
    -------
    str
        The resolved DID.

    Raises
    ------
    IdentityError
        If the handle cannot be resolved.
    """
    with IdentityResolver() as resolver:
        return resolver.resolve_handle(handle)


def resolve_did(did: str) -> dict[str, JsonValue]:
    """Resolve a DID to its DID document using a throwaway resolver.

    Parameters
    ----------
    did : str
        The DID to resolve.

    Returns
    -------
    dict
        The resolved DID document.

    Raises
    ------
    IdentityError
        If the DID cannot be resolved.
    """
    with IdentityResolver() as resolver:
        return resolver.resolve_did(did)


def resolve_pds(did: str) -> str:
    """Resolve a DID to its PDS service endpoint using a throwaway resolver.

    Parameters
    ----------
    did : str
        The DID to resolve.

    Returns
    -------
    str
        The PDS endpoint URL.

    Raises
    ------
    IdentityError
        If the DID cannot be resolved.
    """
    with IdentityResolver() as resolver:
        return resolver.resolve_pds(did)
