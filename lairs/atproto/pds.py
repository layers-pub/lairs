"""Direct PDS record client.

Wraps ``com.atproto.repo.getRecord`` and ``com.atproto.repo.listRecords`` over
the XRPC HTTP interface of a PDS, with ``listRecords`` cursor pagination folded
into a lazy iterator. Responses use the standard ``{uri, cid, value}`` envelope,
modelled here as ``RecordEnvelope``. A generic ``decode`` helper validates an
envelope's ``value`` against any ``dx.Model`` target; ``decode_all`` decodes a
batch and collects per-record validation failures instead of failing fast.

The transport is ``httpx``; the bulk ``com.atproto.sync.getRepo`` CAR path is a
clearly-marked deferred stub. Public reads need no auth.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self

import didactic.api as dx
import httpx

from lairs._types import JsonValue  # noqa: TC001  (runtime: didactic field sort)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from types import TracebackType

__all__ = [
    "PdsClient",
    "QueryParams",
    "RecordDecodeFailure",
    "RecordEnvelope",
    "decode",
    "decode_all",
    "get_record",
    "list_records",
]

type QueryParams = dict[str, str | int | bool]
"""The scalar parameter mapping accepted by an XRPC query.

XRPC query parameters are always JSON scalars (strings, integers, or booleans),
which is narrower than ``JsonValue`` and matches what ``httpx`` accepts for a
query string.
"""

_GET_RECORD_NSID = "com.atproto.repo.getRecord"
"""The XRPC method for fetching a single record."""

_LIST_RECORDS_NSID = "com.atproto.repo.listRecords"
"""The XRPC method for enumerating a collection."""

_GET_REPO_NSID = "com.atproto.sync.getRepo"
"""The XRPC method for bulk CAR export of a whole repository."""

DEFAULT_PAGE_SIZE = 100
"""The default page size requested from ``listRecords``."""


class RecordEnvelope(dx.Model):
    """The standard ATProto record envelope.

    Parameters
    ----------
    uri : str
        The AT-URI of the record.
    cid : str
        The content identifier of the record.
    value : JsonValue
        The record's JSON value, decoded against a generated model on demand.
    """

    uri: str = dx.field(description="AT-URI of the record")
    cid: str = dx.field(description="content identifier of the record")
    value: JsonValue = dx.field(
        default=None,
        description="record value, decoded against a generated model on demand",
    )


class RecordDecodeFailure(dx.Model):
    """A per-record decode failure with diagnostics.

    Parameters
    ----------
    uri : str
        The AT-URI of the record that failed to decode.
    cid : str
        The content identifier of the record that failed to decode.
    error : str
        A human-readable description of the validation failure.
    """

    uri: str = dx.field(description="AT-URI of the record that failed to decode")
    cid: str = dx.field(
        description="content identifier of the record that failed to decode",
    )
    error: str = dx.field(description="human-readable validation failure description")


def decode[T: dx.Model](envelope: RecordEnvelope, model: type[T]) -> T:
    """Decode a single envelope's value into a model instance.

    Parameters
    ----------
    envelope : RecordEnvelope
        The record envelope to decode.
    model : type
        The target ``dx.Model`` subclass.

    Returns
    -------
    T
        The validated model instance.

    Raises
    ------
    didactic.api.ValidationError
        If the envelope's value does not validate against ``model``.
    """
    return model.model_validate_json(json.dumps(_record_object(envelope)))


def _record_object(envelope: RecordEnvelope) -> dict[str, JsonValue]:
    """Narrow an envelope's value to a JSON object for validation.

    The ATProto record-type discriminator ``$type`` is dropped: it is protocol
    metadata that records carry on the wire but the generated models do not
    declare, so leaving it in would fail validation against every real record.

    Parameters
    ----------
    envelope : RecordEnvelope
        The record envelope whose value to narrow.

    Returns
    -------
    dict
        The record value as a JSON object, without the ``$type`` key.

    Raises
    ------
    didactic.api.ValidationError
        If the value is not a JSON object.
    """
    value = envelope.value
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key != "$type"}
    entry = dx.ValidationErrorEntry(
        loc=("value",),
        type="type_error",
        msg=f"record value for {envelope.uri} is not a json object",
    )
    raise dx.ValidationError((entry,))


def decode_all[T: dx.Model](
    envelopes: Sequence[RecordEnvelope],
    model: type[T],
) -> tuple[tuple[T, ...], tuple[RecordDecodeFailure, ...]]:
    """Decode a batch of envelopes, collecting failures.

    Validation failures are gathered into a tuple of ``RecordDecodeFailure``
    models with per-record diagnostics so a single bad record does not abort
    the batch. The result is a ``(records, failures)`` pair; a generic result
    model is not used because didactic does not classify a model field typed by
    an unbound type variable.

    Parameters
    ----------
    envelopes : collections.abc.Sequence of RecordEnvelope
        The record envelopes to decode.
    model : type
        The target ``dx.Model`` subclass.

    Returns
    -------
    tuple
        A ``(records, failures)`` pair: the successfully decoded model instances
        and the per-record decode failures.
    """
    records: list[T] = []
    failures: list[RecordDecodeFailure] = []
    for envelope in envelopes:
        try:
            records.append(
                model.model_validate_json(json.dumps(_record_object(envelope)))
            )
        except dx.ValidationError as exc:
            failures.append(
                RecordDecodeFailure(
                    uri=envelope.uri,
                    cid=envelope.cid,
                    error=str(exc),
                ),
            )
    return tuple(records), tuple(failures)


def _envelope_from_record(record: dict[str, JsonValue]) -> RecordEnvelope:
    """Build a ``RecordEnvelope`` from a raw XRPC record object.

    Parameters
    ----------
    record : dict
        A raw ``{uri, cid, value}`` object from an XRPC response.

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


class PdsClient:
    """An XRPC client over a single PDS, for read-only record access.

    Parameters
    ----------
    endpoint : str
        The base URL of the PDS (for example ``https://pds.example``).
    client : httpx.Client or None, optional
        An injected HTTP client. When omitted, a private client is created and
        closed with this client. Injecting a client lets a session carry auth
        for private reads later; public reads need no auth.
    """

    def __init__(
        self,
        endpoint: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
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
        """Build the XRPC URL for a method NSID.

        Parameters
        ----------
        nsid : str
            The XRPC method NSID.

        Returns
        -------
        str
            The fully qualified XRPC query URL.
        """
        return f"{self._endpoint}/xrpc/{nsid}"

    def get_record(self, repo: str, collection: str, rkey: str) -> RecordEnvelope:
        """Fetch a single record by repo, collection, and rkey.

        Parameters
        ----------
        repo : str
            The repository DID or handle.
        collection : str
            The record collection NSID.
        rkey : str
            The record key.

        Returns
        -------
        RecordEnvelope
            The ``{uri, cid, value}`` record envelope.

        Raises
        ------
        httpx.HTTPStatusError
            If the PDS returns a non-success status.
        """
        params = {"repo": repo, "collection": collection, "rkey": rkey}
        response = self._client.get(
            self._xrpc_url(_GET_RECORD_NSID),
            params=params,
        )
        response.raise_for_status()
        body = response.json()
        record = body if isinstance(body, dict) else {}
        return _envelope_from_record(record)

    def list_records(
        self,
        repo: str,
        collection: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Iterator[RecordEnvelope]:
        """Enumerate records in a collection with cursor pagination.

        Pages are fetched lazily: each page is requested only when the
        consumer advances past the previous page, and iteration stops when the
        PDS stops returning a cursor.

        Parameters
        ----------
        repo : str
            The repository DID or handle.
        collection : str
            The record collection NSID.
        limit : int or None, optional
            The page size requested from the PDS; defaults to the module page
            size.
        cursor : str or None, optional
            An opaque pagination cursor to resume from.

        Yields
        ------
        RecordEnvelope
            Record envelopes, in PDS order, across all pages.

        Raises
        ------
        httpx.HTTPStatusError
            If the PDS returns a non-success status for any page.
        """
        page_size = limit if limit is not None else DEFAULT_PAGE_SIZE
        next_cursor = cursor
        while True:
            params: QueryParams = {
                "repo": repo,
                "collection": collection,
                "limit": page_size,
            }
            if next_cursor is not None:
                params["cursor"] = next_cursor
            response = self._client.get(
                self._xrpc_url(_LIST_RECORDS_NSID),
                params=params,
            )
            response.raise_for_status()
            body = response.json()
            page = body if isinstance(body, dict) else {}
            records = page.get("records")
            if isinstance(records, list):
                for record in records:
                    if isinstance(record, dict):
                        yield _envelope_from_record(record)
            returned_cursor = page.get("cursor")
            if not isinstance(returned_cursor, str) or returned_cursor == "":
                return
            next_cursor = returned_cursor

    def get_repo_car(self, repo: str) -> bytes:
        """Fetch a whole repository as a CAR archive.

        This is the bulk ``com.atproto.sync.getRepo`` path. CAR and DAG-CBOR
        block decoding is deferred; the raw archive bytes are returned for a
        future decoder.

        Parameters
        ----------
        repo : str
            The repository DID.

        Returns
        -------
        bytes
            The CAR archive bytes.

        Raises
        ------
        NotImplementedError
            Always, until CAR / DAG-CBOR decoding lands.
        """
        # deferred: fetching is trivial but decoding the car block store to
        # record envelopes requires a dag-cbor codec that is out of scope for
        # the read milestone; see plan section 6.2.
        _ = (self._endpoint, _GET_REPO_NSID, repo)
        msg = "bulk getRepo CAR decode is deferred"
        raise NotImplementedError(msg)


def get_record(
    endpoint: str,
    repo: str,
    collection: str,
    rkey: str,
) -> RecordEnvelope:
    """Fetch a single record using a throwaway client.

    Parameters
    ----------
    endpoint : str
        The base URL of the PDS.
    repo : str
        The repository DID or handle.
    collection : str
        The record collection NSID.
    rkey : str
        The record key.

    Returns
    -------
    RecordEnvelope
        The record envelope.

    Raises
    ------
    httpx.HTTPStatusError
        If the PDS returns a non-success status.
    """
    with PdsClient(endpoint) as client:
        return client.get_record(repo, collection, rkey)


def list_records(
    endpoint: str,
    repo: str,
    collection: str,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> list[RecordEnvelope]:
    """List records using a throwaway client, draining all pages.

    The lazy iterator is fully consumed here so the throwaway client can close;
    use ``PdsClient.list_records`` for true streaming over an open client.

    Parameters
    ----------
    endpoint : str
        The base URL of the PDS.
    repo : str
        The repository DID or handle.
    collection : str
        The record collection NSID.
    limit : int or None, optional
        The page size requested from the PDS.
    cursor : str or None, optional
        An opaque pagination cursor to resume from.

    Returns
    -------
    list of RecordEnvelope
        Every record envelope across all pages.

    Raises
    ------
    httpx.HTTPStatusError
        If the PDS returns a non-success status for any page.
    """
    with PdsClient(endpoint) as client:
        return list(
            client.list_records(repo, collection, limit=limit, cursor=cursor),
        )
