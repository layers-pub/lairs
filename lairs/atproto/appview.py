"""Optional appview XRPC query client.

A thin client over the Layers appview query API (``pub.layers.*.get*`` and
``list*``) used for discovery and cross-ref resolution without walking PDSes.
The appview is an accelerator only: lairs works with it off, where direct PDS
access is the contract. Responses use the same ``{uri, cid, value}`` envelope as
the PDS, so they decode through the same generated models.

The transport is ``httpx``; the endpoint is configurable. Public queries need no
auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import httpx

from lairs.atproto.pds import QueryParams, RecordEnvelope, RecordNotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

    from lairs._types import JsonValue

__all__ = ["AppviewClient"]

_NSID_PREFIX = "pub.layers."
"""The NSID prefix the appview exposes its Layers query methods under."""


def _envelope_from_record(record: dict[str, JsonValue]) -> RecordEnvelope:
    """Build a ``RecordEnvelope`` from a raw appview record object.

    Parameters
    ----------
    record : dict
        A raw ``{uri, cid, value}`` object from an appview response.

    Returns
    -------
    RecordEnvelope
        The modelled envelope.
    """
    uri = record.get("uri")
    cid = record.get("cid")
    return RecordEnvelope(
        uri=uri if isinstance(uri, str) else "",
        cid=cid if isinstance(cid, str) else "",
        value=record.get("value"),
    )


class AppviewClient:
    """A thin XRPC client over the Layers appview query API.

    Parameters
    ----------
    endpoint : str
        The base URL of the appview XRPC service.
    client : httpx.Client or None, optional
        An injected HTTP client. When omitted, a private client is created and
        closed with this client. Public queries need no auth.
    """

    def __init__(
        self,
        endpoint: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None

    def __enter__(self) -> Self:
        """Enter the client as a context manager.

        Returns
        -------
        Self
            This client.
        """
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Close the client on context-manager exit.

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
        """Close the underlying HTTP client if this client owns it."""
        if self._owns_client:
            self._client.close()

    def _xrpc_url(self, nsid: str) -> str:
        """Build the XRPC URL for a Layers query NSID.

        Parameters
        ----------
        nsid : str
            The query method NSID. A bare name (for example
            ``corpus.listCorpora``) is prefixed with ``pub.layers.``.

        Returns
        -------
        str
            The fully qualified XRPC query URL.
        """
        full = nsid if nsid.startswith(_NSID_PREFIX) else f"{_NSID_PREFIX}{nsid}"
        return f"{self.endpoint}/xrpc/{full}"

    def query(
        self,
        nsid: str,
        params: QueryParams,
    ) -> dict[str, JsonValue]:
        """Issue an XRPC query against the appview.

        Parameters
        ----------
        nsid : str
            The query method NSID (for example ``corpus.listCorpora``).
        params : dict
            The query parameters.

        Returns
        -------
        dict
            The decoded XRPC response body.

        Raises
        ------
        httpx.HTTPStatusError
            If the appview returns a non-success status.
        """
        response = self._client.get(self._xrpc_url(nsid), params=params)
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else {}

    def get(
        self,
        nsid: str,
        params: QueryParams,
    ) -> RecordEnvelope:
        """Issue a ``get*`` query and return its record envelope.

        Parameters
        ----------
        nsid : str
            The ``get*`` method NSID (for example ``corpus.getCorpus``).
        params : dict
            The query parameters.

        Returns
        -------
        RecordEnvelope
            The ``{uri, cid, value}`` record envelope.

        Raises
        ------
        httpx.HTTPStatusError
            If the appview returns a non-success status.
        RecordNotFoundError
            If the appview returns a ``200`` whose body is not a usable record
            object (an empty or malformed body with no string ``uri``).
        """
        body = self.query(nsid, params)
        if not isinstance(body.get("uri"), str):
            msg = f"appview query {nsid} returned no usable record"
            raise RecordNotFoundError(msg)
        return _envelope_from_record(body)

    def list(
        self,
        nsid: str,
        params: QueryParams,
        *,
        results_key: str = "records",
        cursor: str | None = None,
    ) -> Iterator[RecordEnvelope]:
        """Issue a ``list*`` query and lazily iterate its record envelopes.

        Cursor pagination is folded into the iterator: each page is fetched
        only when the consumer advances past the previous one, and iteration
        stops when the appview stops returning a cursor.

        Parameters
        ----------
        nsid : str
            The ``list*`` method NSID (for example ``corpus.listCorpora``).
        params : dict
            The query parameters, excluding the cursor.
        results_key : str, optional
            The response key holding the records array.
        cursor : str or None, optional
            An opaque pagination cursor to resume from.

        Yields
        ------
        RecordEnvelope
            Record envelopes, in appview order, across all pages.

        Raises
        ------
        httpx.HTTPStatusError
            If the appview returns a non-success status for any page.
        """
        next_cursor = cursor
        while True:
            page_params = dict(params)
            if next_cursor is not None:
                page_params["cursor"] = next_cursor
            body = self.query(nsid, page_params)
            records = body.get(results_key)
            if isinstance(records, list):
                for record in records:
                    if isinstance(record, dict):
                        yield _envelope_from_record(record)
            returned_cursor = body.get("cursor")
            if not isinstance(returned_cursor, str) or returned_cursor == "":
                return
            next_cursor = returned_cursor
