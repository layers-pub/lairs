"""Single and bulk publishing, and the local-VCS-to-PDS workflow.

The write path mirrors the read client style of :mod:`lairs.atproto` but lives
here because all writes are owned by the authoring component. A
:class:`WriteClient` wraps ``com.atproto.repo.uploadBlob`` /
``createRecord`` / ``putRecord`` / ``deleteRecord`` / ``applyWrites`` over an
injected, authenticated ``httpx`` client; OAuth itself is not implemented here
(the session is injected), but the surface is structured for explicit write
scopes and every write is scoped to the one authenticated repository.

The bulk path is ``applyWrites``. Records are ordered by cross-reference
dependency (media before referrers; expressions before segmentations,
annotations, and memberships; ontologies and personas before the layers that
cite them), so a referenced record always commits before its referrer. Writes
are chunked to a PDS batch limit, retried idempotently against deterministic
rkeys, and reported back as a per-record result set
(created / updated / skipped / failed with reasons).

:func:`publish` maps a local Repository revision to the minimal ``applyWrites``
plan by diffing the revision against what is already on the PDS (by AT-URI and
CID); ``dry_run`` returns the plan without sending it. :func:`pull` ingests an
account's Layers records into a Repository for a git-like round trip.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from typing import TYPE_CHECKING, Self

import didactic.api as dx
import httpx
import libipld
from multiformats import CID, multihash

from lairs._types import JsonValue  # noqa: TC001  (runtime: didactic field sort)
from lairs.atproto.pds import PdsClient

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from types import TracebackType

    from lairs.store.repository import Repository

__all__ = [
    "PublishPlan",
    "WriteClient",
    "WriteOp",
    "WriteResult",
    "apply_writes",
    "collection_of",
    "order_writes",
    "publish",
    "pull",
]

_UPLOAD_BLOB_NSID = "com.atproto.repo.uploadBlob"
"""The XRPC method for uploading a blob."""

_CREATE_RECORD_NSID = "com.atproto.repo.createRecord"
"""The XRPC method for creating a single record with an auto rkey."""

_PUT_RECORD_NSID = "com.atproto.repo.putRecord"
"""The XRPC method for upserting a single record at an explicit rkey."""

_DELETE_RECORD_NSID = "com.atproto.repo.deleteRecord"
"""The XRPC method for deleting a single record."""

_APPLY_WRITES_NSID = "com.atproto.repo.applyWrites"
"""The XRPC method for applying a batch of writes."""

MAX_BLOB_SIZE = 100 * 1024 * 1024
"""The 100MB blob size cap honoured before upload."""

APPLY_WRITES_CHUNK = 200
"""The maximum number of writes sent in one ``applyWrites`` batch."""

# the dependency tier of each collection NSID. lower tiers are published first
# so a referenced record always commits before its referrer. tiers mirror the
# cross-reference structure of the lexicons (plan section 6b.3).
_DEPENDENCY_TIERS: dict[str, int] = {
    # tier 0: standalone vocabulary and provenance, cited by everything.
    "pub.layers.ontology.ontology": 0,
    "pub.layers.ontology.typeDef": 0,
    "pub.layers.persona.persona": 0,
    "pub.layers.eprint.eprint": 0,
    "pub.layers.eprint.dataLink": 0,
    "pub.layers.media.media": 0,
    # tier 1: expressions, which segmentations and annotations anchor into.
    "pub.layers.expression.expression": 1,
    # tier 2: token-level structure over expressions.
    "pub.layers.segmentation.segmentation": 2,
    # tier 3: annotations, graphs, and corpora over expressions and tokens.
    "pub.layers.annotation.annotationLayer": 3,
    "pub.layers.annotation.clusterSet": 3,
    "pub.layers.graph.graphNode": 3,
    "pub.layers.graph.graphEdge": 3,
    "pub.layers.graph.graphEdgeSet": 3,
    "pub.layers.alignment.alignment": 3,
    "pub.layers.corpus.corpus": 3,
    "pub.layers.resource.collection": 3,
    "pub.layers.resource.template": 3,
    # tier 4: records that reference tier-3 records.
    "pub.layers.corpus.membership": 4,
    "pub.layers.resource.entry": 4,
    "pub.layers.resource.filling": 4,
    "pub.layers.resource.collectionMembership": 4,
    "pub.layers.resource.templateComposition": 4,
    "pub.layers.judgment.experimentDef": 4,
    "pub.layers.judgment.judgmentSet": 4,
    "pub.layers.judgment.agreementReport": 4,
    "pub.layers.changelog.entry": 4,
}

_DEFAULT_TIER = 3
"""The dependency tier used for a collection not in the explicit table."""

# collection NSID -> (generated namespace module, record model class name). the
# registry mirrors the 26 vendored record types; it is used to decode pulled
# records back into the generated models before staging them in a Repository.
_RECORD_MODELS: dict[str, tuple[str, str]] = {
    "pub.layers.alignment.alignment": ("alignment", "Alignment"),
    "pub.layers.annotation.annotationLayer": ("annotation", "AnnotationLayer"),
    "pub.layers.annotation.clusterSet": ("annotation", "ClusterSet"),
    "pub.layers.changelog.entry": ("changelog", "Entry"),
    "pub.layers.corpus.corpus": ("corpus", "Corpus"),
    "pub.layers.corpus.membership": ("corpus", "Membership"),
    "pub.layers.eprint.dataLink": ("eprint", "DataLink"),
    "pub.layers.eprint.eprint": ("eprint", "Eprint"),
    "pub.layers.expression.expression": ("expression", "Expression"),
    "pub.layers.graph.graphEdge": ("graph", "GraphEdge"),
    "pub.layers.graph.graphEdgeSet": ("graph", "GraphEdgeSet"),
    "pub.layers.graph.graphNode": ("graph", "GraphNode"),
    "pub.layers.judgment.agreementReport": ("judgment", "AgreementReport"),
    "pub.layers.judgment.experimentDef": ("judgment", "ExperimentDef"),
    "pub.layers.judgment.judgmentSet": ("judgment", "JudgmentSet"),
    "pub.layers.media.media": ("media", "Media"),
    "pub.layers.ontology.ontology": ("ontology", "Ontology"),
    "pub.layers.ontology.typeDef": ("ontology", "TypeDef"),
    "pub.layers.persona.persona": ("persona", "Persona"),
    "pub.layers.resource.collection": ("resource", "Collection"),
    "pub.layers.resource.collectionMembership": ("resource", "CollectionMembership"),
    "pub.layers.resource.entry": ("resource", "Entry"),
    "pub.layers.resource.filling": ("resource", "Filling"),
    "pub.layers.resource.template": ("resource", "Template"),
    "pub.layers.resource.templateComposition": ("resource", "TemplateComposition"),
    "pub.layers.segmentation.segmentation": ("segmentation", "Segmentation"),
}
"""The 26 Layers record collections and their generated model classes."""


def _model_for(collection: str) -> type[dx.Model] | None:
    """Return the generated model class for a collection NSID.

    Parameters
    ----------
    collection : str
        The collection NSID.

    Returns
    -------
    type of didactic.api.Model or None
        The record model class, or ``None`` for an unknown collection.
    """
    entry = _RECORD_MODELS.get(collection)
    if entry is None:
        return None
    namespace, class_name = entry
    module = importlib.import_module(f"lairs.records._generated.{namespace}")
    model = getattr(module, class_name, None)
    if isinstance(model, type) and issubclass(model, dx.Model):
        return model
    return None


class WriteError(RuntimeError):
    """Raised when a write cannot be performed.

    Wraps transport and validation failures behind a single error so callers do
    not have to discriminate transport-specific exceptions.
    """


def collection_of(uri: str) -> str:
    """Return the collection NSID embedded in an AT-URI.

    An AT-URI has the form ``at://<authority>/<collection>/<rkey>``; the
    collection segment is the lexicon NSID.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The collection NSID, or the empty string when none is present.
    """
    body = uri.removeprefix("at://")
    parts = body.split("/")
    minimum_with_collection = 2
    if len(parts) >= minimum_with_collection:
        return parts[1]
    return ""


def _rkey_of(uri: str) -> str:
    """Return the rkey embedded in an AT-URI, or the empty string.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The rkey segment, or the empty string when none is present.
    """
    body = uri.removeprefix("at://")
    parts = body.split("/")
    minimum_with_rkey = 3
    if len(parts) >= minimum_with_rkey:
        return parts[2]
    return ""


def _tier_of(collection: str) -> int:
    """Return the dependency tier for a collection NSID.

    Parameters
    ----------
    collection : str
        The collection NSID.

    Returns
    -------
    int
        The tier; unknown collections default to the middle tier.
    """
    return _DEPENDENCY_TIERS.get(collection, _DEFAULT_TIER)


def deterministic_rkey(value: Mapping[str, JsonValue]) -> str:
    """Derive a deterministic rkey from a record value.

    A stable rkey makes re-publishing idempotent: a second publish of the same
    content upserts the same record rather than creating a duplicate. The rkey
    is the first 24 hex characters of the SHA-256 of the canonical JSON of the
    value, which is within ATProto's rkey syntax.

    Parameters
    ----------
    value : collections.abc.Mapping
        The record value to hash.

    Returns
    -------
    str
        A 24-character lowercase-hex rkey.
    """
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    rkey_length = 24
    return digest[:rkey_length]


def content_address(data: bytes) -> str:
    """Return a stable content address for blob bytes.

    Used to deduplicate blob uploads within a publish session so re-publishing
    the same media is idempotent.

    Parameters
    ----------
    data : bytes
        The blob bytes.

    Returns
    -------
    str
        The hex SHA-256 digest of the bytes.
    """
    return hashlib.sha256(data).hexdigest()


class WriteOp(dx.Model):
    """A single planned write operation against a repository.

    Attributes
    ----------
    action : str
        The operation: ``create``, ``update``, or ``delete``.
    collection : str
        The collection NSID the record belongs to.
    rkey : str
        The record key the operation targets.
    uri : str
        The AT-URI the operation targets, when known.
    cid : str or None, optional
        The content identifier of the record value, when known.
    value : JsonValue
        The record value for create and update operations.
    """

    action: str = dx.field(description="create, update, or delete")
    collection: str = dx.field(description="collection NSID of the record")
    rkey: str = dx.field(description="record key the operation targets")
    uri: str = dx.field(default="", description="AT-URI the operation targets")
    cid: str | None = dx.field(
        default=None,
        description="content identifier of the record value, when known",
    )
    value: JsonValue = dx.field(
        default=None,
        description="record value for create and update operations",
    )


class WriteResult(dx.Model):
    """The per-record outcome of a write.

    Attributes
    ----------
    uri : str
        The AT-URI of the record.
    status : str
        The outcome: ``created``, ``updated``, ``skipped``, or ``failed``.
    cid : str or None, optional
        The content identifier returned by the PDS, when the write succeeded.
    reason : str or None, optional
        A human-readable reason for a skipped or failed write.
    """

    uri: str = dx.field(description="AT-URI of the record")
    status: str = dx.field(description="created, updated, skipped, or failed")
    cid: str | None = dx.field(
        default=None,
        description="content identifier returned by the PDS, when successful",
    )
    reason: str | None = dx.field(
        default=None,
        description="reason for a skipped or failed write",
    )


class PublishPlan(dx.Model):
    """The minimal write plan to make a PDS match a revision.

    Attributes
    ----------
    repo : str
        The target repository DID.
    revision : str
        The local revision the plan was computed from.
    creates : tuple of WriteOp
        Records present in the revision but not on the PDS.
    updates : tuple of WriteOp
        Records present in both whose value (CID) differs.
    deletes : tuple of WriteOp
        Records on the PDS but absent from the revision.
    """

    repo: str = dx.field(description="target repository DID")
    revision: str = dx.field(description="local revision the plan was computed from")
    creates: tuple[WriteOp, ...] = dx.field(
        default_factory=tuple,
        description="records to create",
    )
    updates: tuple[WriteOp, ...] = dx.field(
        default_factory=tuple,
        description="records to update",
    )
    deletes: tuple[WriteOp, ...] = dx.field(
        default_factory=tuple,
        description="records to delete",
    )

    def ordered_writes(self) -> tuple[WriteOp, ...]:
        """Return every write, ordered for safe application.

        Deletes are emitted first in reverse dependency order (referrers before
        their targets), then creates and updates in forward dependency order
        (targets before referrers), so the PDS never holds a dangling
        reference during application.

        Returns
        -------
        tuple of WriteOp
            The full write set in application order.
        """
        deletes = sorted(
            self.deletes,
            key=lambda op: (-_tier_of(op.collection), op.uri),
        )
        upserts = order_writes((*self.creates, *self.updates))
        return (*deletes, *upserts)

    def is_empty(self) -> bool:
        """Return whether the plan contains no writes.

        Returns
        -------
        bool
            ``True`` when there is nothing to create, update, or delete.
        """
        return not (self.creates or self.updates or self.deletes)


def order_writes(writes: Sequence[WriteOp]) -> tuple[WriteOp, ...]:
    """Order create/update writes by cross-reference dependency.

    Writes are sorted by their collection's dependency tier (lower first) and
    then by AT-URI for determinism, so a referenced record always precedes its
    referrer within one ordered batch.

    Parameters
    ----------
    writes : collections.abc.Sequence of WriteOp
        The writes to order.

    Returns
    -------
    tuple of WriteOp
        The writes in dependency order.
    """
    return tuple(
        sorted(writes, key=lambda op: (_tier_of(op.collection), op.uri)),
    )


def _chunk[T](items: Sequence[T], size: int) -> Iterator[tuple[T, ...]]:
    """Yield successive fixed-size chunks of a sequence.

    Parameters
    ----------
    items : collections.abc.Sequence
        The sequence to chunk.
    size : int
        The maximum chunk size.

    Yields
    ------
    tuple
        Successive chunks, the last possibly shorter than ``size``.
    """
    for start in range(0, len(items), size):
        yield tuple(items[start : start + size])


class WriteClient:
    """An XRPC client for writes to the authenticated user's own repository.

    The client mirrors the read-client style of :mod:`lairs.atproto` but only
    ever targets the one authenticated repository. OAuth is not implemented
    here: an authenticated ``httpx`` client (carrying the session's bearer
    token and write scopes) is injected. Every write call passes the owning
    repository DID so the safety scope is explicit at the call site.

    Parameters
    ----------
    endpoint : str
        The base URL of the PDS (for example ``https://pds.example``).
    repo : str
        The authenticated repository DID; all writes target this repository.
    client : httpx.Client or None, optional
        An injected, authenticated HTTP client. When omitted, a private,
        unauthenticated client is created (useful only against a mock
        transport); real writes require an injected authenticated client.
    """

    def __init__(
        self,
        endpoint: str,
        repo: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._repo = repo
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None
        # content-address -> blob ref json, to deduplicate uploads in a session.
        self._blob_cache: dict[str, JsonValue] = {}

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

    @property
    def repo(self) -> str:
        """Return the authenticated repository DID this client writes to.

        Returns
        -------
        str
            The owning repository DID.
        """
        return self._repo

    def _xrpc_url(self, nsid: str) -> str:
        """Build the XRPC URL for a method NSID.

        Parameters
        ----------
        nsid : str
            The XRPC method NSID.

        Returns
        -------
        str
            The fully qualified XRPC procedure URL.
        """
        return f"{self._endpoint}/xrpc/{nsid}"

    def _post(self, nsid: str, body: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        """POST an XRPC procedure body and return the JSON response object.

        Parameters
        ----------
        nsid : str
            The XRPC method NSID.
        body : collections.abc.Mapping
            The JSON request body.

        Returns
        -------
        dict
            The JSON response object.

        Raises
        ------
        WriteError
            If the PDS returns a non-success status or a non-object body.
        """
        try:
            response = self._client.post(self._xrpc_url(nsid), json=dict(body))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"{nsid} failed: {exc}"
            raise WriteError(msg) from exc
        parsed = response.json()
        if not isinstance(parsed, dict):
            msg = f"{nsid} returned a non-object body"
            raise WriteError(msg)
        return parsed

    def upload_blob(self, data: bytes, mime_type: str) -> JsonValue:
        """Upload blob bytes and return the PDS blob reference.

        Honors the 100MB size cap and content-addresses the upload so the same
        bytes uploaded twice in a session reuse the first blob reference, making
        re-publishing idempotent. The returned value is the raw ATProto blob
        reference object the PDS emits, ready to embed in a record value.

        Parameters
        ----------
        data : bytes
            The blob bytes to upload.
        mime_type : str
            The MIME type of the blob.

        Returns
        -------
        JsonValue
            The blob reference object returned by the PDS.

        Raises
        ------
        WriteError
            If the blob exceeds the size cap or the upload fails.
        """
        if len(data) > MAX_BLOB_SIZE:
            msg = f"blob is {len(data)} bytes, over the {MAX_BLOB_SIZE}-byte cap"
            raise WriteError(msg)
        address = content_address(data)
        cached = self._blob_cache.get(address)
        if cached is not None:
            return cached
        try:
            response = self._client.post(
                self._xrpc_url(_UPLOAD_BLOB_NSID),
                content=data,
                headers={"content-type": mime_type},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"uploadBlob failed: {exc}"
            raise WriteError(msg) from exc
        parsed = response.json()
        blob = parsed.get("blob") if isinstance(parsed, dict) else None
        self._blob_cache[address] = blob
        return blob

    def create_record(
        self,
        collection: str,
        value: Mapping[str, JsonValue],
        *,
        rkey: str | None = None,
    ) -> WriteResult:
        """Create a single record, optionally at an explicit rkey.

        Parameters
        ----------
        collection : str
            The collection NSID.
        value : collections.abc.Mapping
            The record value.
        rkey : str or None, optional
            An explicit rkey; the PDS assigns a TID when omitted.

        Returns
        -------
        WriteResult
            The per-record outcome.
        """
        body: dict[str, JsonValue] = {
            "repo": self._repo,
            "collection": collection,
            "record": dict(value),
        }
        if rkey is not None:
            body["rkey"] = rkey
        parsed = self._post(_CREATE_RECORD_NSID, body)
        uri = parsed.get("uri")
        cid = parsed.get("cid")
        return WriteResult(
            uri=uri if isinstance(uri, str) else "",
            status="created",
            cid=cid if isinstance(cid, str) else None,
        )

    def put_record(
        self,
        collection: str,
        rkey: str,
        value: Mapping[str, JsonValue],
    ) -> WriteResult:
        """Upsert a single record at an explicit rkey.

        Parameters
        ----------
        collection : str
            The collection NSID.
        rkey : str
            The record key.
        value : collections.abc.Mapping
            The record value.

        Returns
        -------
        WriteResult
            The per-record outcome.
        """
        body: dict[str, JsonValue] = {
            "repo": self._repo,
            "collection": collection,
            "rkey": rkey,
            "record": dict(value),
        }
        parsed = self._post(_PUT_RECORD_NSID, body)
        uri = parsed.get("uri")
        cid = parsed.get("cid")
        return WriteResult(
            uri=uri if isinstance(uri, str) else "",
            status="updated",
            cid=cid if isinstance(cid, str) else None,
        )

    def delete_record(self, collection: str, rkey: str) -> WriteResult:
        """Delete a single record.

        Parameters
        ----------
        collection : str
            The collection NSID.
        rkey : str
            The record key.

        Returns
        -------
        WriteResult
            The per-record outcome.
        """
        body: dict[str, JsonValue] = {
            "repo": self._repo,
            "collection": collection,
            "rkey": rkey,
        }
        self._post(_DELETE_RECORD_NSID, body)
        uri = f"at://{self._repo}/{collection}/{rkey}"
        return WriteResult(uri=uri, status="deleted")

    def apply_writes(self, writes: Sequence[WriteOp]) -> tuple[WriteResult, ...]:
        """Apply writes in dependency-ordered, retried, chunked batches.

        Writes are ordered so a referenced record precedes its referrer, sent
        in chunks within the PDS batch limit, and retried once per chunk via
        idempotent ``putRecord`` upserts on deterministic rkeys when the batch
        call fails, so a partial failure can be safely resumed. Each input
        write yields exactly one :class:`WriteResult`.

        Parameters
        ----------
        writes : collections.abc.Sequence of WriteOp
            The writes to apply.

        Returns
        -------
        tuple of WriteResult
            One outcome per input write.
        """
        ordered = order_writes(writes)
        results: list[WriteResult] = []
        for chunk in _chunk(ordered, APPLY_WRITES_CHUNK):
            results.extend(self._apply_chunk(chunk))
        return tuple(results)

    def _apply_chunk(self, chunk: Sequence[WriteOp]) -> tuple[WriteResult, ...]:
        """Apply one chunk, retrying per-record on a batch failure.

        Parameters
        ----------
        chunk : collections.abc.Sequence of WriteOp
            The writes in this batch.

        Returns
        -------
        tuple of WriteResult
            One outcome per write in the chunk.
        """
        body: dict[str, JsonValue] = {
            "repo": self._repo,
            "writes": [_write_op_to_json(op) for op in chunk],
        }
        try:
            self._post(_APPLY_WRITES_NSID, body)
        except WriteError:
            return self._retry_chunk(chunk)
        return tuple(
            WriteResult(
                uri=op.uri,
                status="created" if op.action == "create" else op.action + "d",
            )
            for op in chunk
        )

    def _retry_chunk(self, chunk: Sequence[WriteOp]) -> tuple[WriteResult, ...]:
        """Retry a failed chunk one write at a time, idempotently.

        Creates and updates are retried as ``putRecord`` upserts on their rkey,
        so a record already written by the partially-applied batch is upserted
        rather than duplicated. Per-record failures are captured, not raised.

        Parameters
        ----------
        chunk : collections.abc.Sequence of WriteOp
            The writes to retry.

        Returns
        -------
        tuple of WriteResult
            One outcome per write, with failures reported per record.
        """
        results: list[WriteResult] = []
        for op in chunk:
            try:
                results.append(self._retry_one(op))
            except WriteError as exc:
                results.append(
                    WriteResult(uri=op.uri, status="failed", reason=str(exc)),
                )
        return tuple(results)

    def _retry_one(self, op: WriteOp) -> WriteResult:
        """Retry a single write idempotently.

        Parameters
        ----------
        op : WriteOp
            The write to retry.

        Returns
        -------
        WriteResult
            The per-record outcome.
        """
        if op.action == "delete":
            return self.delete_record(op.collection, op.rkey)
        value = op.value if isinstance(op.value, dict) else {}
        return self.put_record(op.collection, op.rkey, value)


def _write_op_to_json(op: WriteOp) -> dict[str, JsonValue]:
    """Encode a write op as an ``applyWrites`` operation object.

    Parameters
    ----------
    op : WriteOp
        The write op to encode.

    Returns
    -------
    dict
        The ``applyWrites`` operation object, with the ``$type`` discriminator.
    """
    action_types = {
        "create": "com.atproto.repo.applyWrites#create",
        "update": "com.atproto.repo.applyWrites#update",
        "delete": "com.atproto.repo.applyWrites#delete",
    }
    encoded: dict[str, JsonValue] = {
        "$type": action_types.get(op.action, op.action),
        "collection": op.collection,
        "rkey": op.rkey,
    }
    if op.action != "delete":
        encoded["value"] = op.value
    return encoded


def apply_writes(
    repo: str,
    writes: Sequence[WriteOp],
    *,
    endpoint: str,
    client: httpx.Client | None = None,
) -> tuple[WriteResult, ...]:
    """Apply a batch of writes to a repo, ordered by dependency.

    Parameters
    ----------
    repo : str
        The authenticated repository DID.
    writes : collections.abc.Sequence of WriteOp
        The create, update, and delete operations to apply.
    endpoint : str
        The base URL of the PDS.
    client : httpx.Client or None, optional
        An injected, authenticated HTTP client.

    Returns
    -------
    tuple of WriteResult
        A per-record result set (created, updated, deleted, or failed).
    """
    with WriteClient(endpoint, repo, client) as write_client:
        return write_client.apply_writes(writes)


def _value_with_type(value: JsonValue, collection: str) -> JsonValue:
    """Ensure a record value carries its ``$type`` discriminator.

    ATProto records embed their collection NSID as ``$type``; the generated
    model dump does not, so it is injected here for the write value.

    Parameters
    ----------
    value : JsonValue
        The record value.
    collection : str
        The collection NSID.

    Returns
    -------
    JsonValue
        The value with ``$type`` set to the collection NSID.
    """
    if not isinstance(value, dict):
        return value
    typed = dict(value)
    typed.setdefault("$type", collection)
    return typed


def _record_cid(value: JsonValue) -> str:
    """Return the ATProto record CID for a value.

    The CID is a CIDv1 over the DAG-CBOR encoding of the value with a sha-256
    multihash and the dag-cbor codec, computed the way a PDS computes the CID it
    reports for a stored record. Computing it the same way lets the publish diff
    detect an unchanged record by CID equality.

    Parameters
    ----------
    value : JsonValue
        The record value, including its ``$type``.

    Returns
    -------
    str
        The record's CIDv1 string.
    """
    digest = multihash.digest(libipld.encode_dag_cbor(value), "sha2-256")
    return str(CID("base32", 1, "dag-cbor", digest))


def _pds_state(repo: Repository, revision: str) -> dict[str, str]:
    """Return the local AT-URI to CID map at a revision.

    Each value's CID is computed the way a PDS computes it, so the publish diff
    detects an unchanged record by CID equality against the PDS's reported CIDs,
    and a re-publish of an unchanged revision is a no-op.

    Parameters
    ----------
    repo : Repository
        The local repository.
    revision : str
        The revision to read.

    Returns
    -------
    dict of str to str
        A mapping from AT-URI to the record CID.
    """
    # resolve the ref so an unknown revision fails loudly; the working-tree
    # store is single-checkout, so the staged values are the revision values.
    repo.resolve(revision)
    state: dict[str, str] = {}
    for uri in repo.staged_uris():
        raw = repo.load_raw(uri)
        if isinstance(raw, dict):
            state[uri] = _record_cid(_value_with_type(raw, collection_of(uri)))
    return state


def _fetch_pds_cids(
    repo: str,
    *,
    endpoint: str,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """Return the AT-URI to CID map currently on a PDS for Layers records.

    Parameters
    ----------
    repo : str
        The repository DID to inspect.
    endpoint : str
        The base URL of the PDS.
    client : httpx.Client or None, optional
        An injected HTTP client; a private one is created when omitted.

    Returns
    -------
    dict of str to str
        A mapping from AT-URI to the PDS-reported record CID.
    """
    cids: dict[str, str] = {}
    with PdsClient(endpoint, client) as pds_client:
        for collection in _RECORD_MODELS:
            try:
                for envelope in pds_client.list_records(repo, collection):
                    cids[envelope.uri] = envelope.cid
            except httpx.HTTPError:
                # a collection with no records may 400/404; treat as empty.
                continue
    return cids


def plan_publish(
    repo: Repository,
    revision: str,
    *,
    to: str,
    pds_cids: Mapping[str, str],
) -> PublishPlan:
    """Compute the minimal write plan against a known PDS state.

    This is the offline core of :func:`publish`: given the PDS's current
    AT-URI to CID map, it diffs the local revision and emits the create,
    update, and delete operations needed to make the PDS match.

    Parameters
    ----------
    repo : Repository
        The local repository holding the revision.
    revision : str
        The revision (commit or tag) to publish.
    to : str
        The target repository DID.
    pds_cids : collections.abc.Mapping
        The AT-URI to CID map currently on the PDS.

    Returns
    -------
    PublishPlan
        The minimal create/update/delete plan.
    """
    local = _pds_state(repo, revision)
    creates: list[WriteOp] = []
    updates: list[WriteOp] = []
    for uri, local_cid in local.items():
        collection = collection_of(uri)
        raw = repo.load_raw(uri)
        value = _value_with_type(raw, collection)
        if uri not in pds_cids:
            creates.append(
                WriteOp(
                    action="create",
                    collection=collection,
                    rkey=_rkey_of(uri),
                    uri=uri,
                    cid=local_cid,
                    value=value,
                ),
            )
        elif pds_cids[uri] != local_cid:
            updates.append(
                WriteOp(
                    action="update",
                    collection=collection,
                    rkey=_rkey_of(uri),
                    uri=uri,
                    cid=local_cid,
                    value=value,
                ),
            )
    deletes = [
        WriteOp(
            action="delete",
            collection=collection_of(uri),
            rkey=_rkey_of(uri),
            uri=uri,
        )
        for uri in pds_cids
        if uri not in local
    ]
    return PublishPlan(
        repo=to,
        revision=revision,
        creates=order_writes(creates),
        updates=order_writes(updates),
        deletes=tuple(deletes),
    )


def publish(  # noqa: PLR0913  (the publish workflow needs these distinct knobs)
    repo: Repository,
    revision: str,
    *,
    to: str,
    endpoint: str | None = None,
    client: httpx.Client | None = None,
    dry_run: bool = False,
) -> PublishPlan:
    """Publish a Repository revision to a PDS as the minimal write set.

    The target revision is diffed against what is already on the PDS (by AT-URI
    and CID) and the minimal ``applyWrites`` plan is emitted. When ``dry_run``
    is ``True`` the plan is returned without sending any writes. Otherwise the
    plan's writes are applied in dependency order (via
    :meth:`PublishPlan.ordered_writes`) and the computed plan is returned for
    inspection.

    Parameters
    ----------
    repo : Repository
        The local repository holding the revision.
    revision : str
        The revision (commit or tag) to publish.
    to : str
        The target repository DID.
    endpoint : str or None, optional
        The base URL of the PDS; required when ``dry_run`` is ``False`` or when
        diffing against the live PDS.
    client : httpx.Client or None, optional
        An injected, authenticated HTTP client used for the diff and the
        writes.
    dry_run : bool, optional
        If ``True``, compute and return the plan without sending writes.

    Returns
    -------
    PublishPlan
        The computed plan; its writes are applied when ``dry_run`` is ``False``.

    Raises
    ------
    WriteError
        If a live publish is requested without a PDS endpoint.
    """
    pds_cids = (
        _fetch_pds_cids(to, endpoint=endpoint, client=client)
        if endpoint is not None
        else {}
    )
    plan = plan_publish(repo, revision, to=to, pds_cids=pds_cids)
    if dry_run:
        return plan
    if endpoint is None:
        msg = "a live publish requires a PDS endpoint"
        raise WriteError(msg)
    with WriteClient(endpoint, to, client) as write_client:
        write_client.apply_writes(plan.ordered_writes())
    return plan


def pull(
    did: str,
    *,
    endpoint: str,
    into: Repository,
    client: httpx.Client | None = None,
) -> Repository:
    """Ingest a PDS account's Layers records into a Repository.

    Each Layers collection is enumerated over the PDS read client and every
    record value is decoded against its generated model and staged into the
    repository under its AT-URI, giving a git-like round trip: an author can
    pull, branch, modify, diff, and publish back. A record that fails to
    validate is skipped rather than aborting the pull.

    Parameters
    ----------
    did : str
        The account DID to pull from.
    endpoint : str
        The base URL of the account's PDS.
    into : Repository
        The repository to populate; its working tree is staged in place.
    client : httpx.Client or None, optional
        An injected HTTP client for the PDS reads; a private one is created when
        omitted.

    Returns
    -------
    Repository
        The populated repository (the same handle as ``into``).
    """
    with PdsClient(endpoint, client) as pds_client:
        for collection, model in _record_collections():
            try:
                envelopes = list(pds_client.list_records(did, collection))
            except httpx.HTTPError:
                continue
            for envelope in envelopes:
                if not isinstance(envelope.value, dict):
                    continue
                try:
                    # decode via the json path: refined types such as datetime
                    # round-trip from their string form there, not from a dict.
                    record = model.model_validate_json(json.dumps(envelope.value))
                except dx.ValidationError:
                    continue
                into.save(envelope.uri, record)
    return into


def _record_collections() -> Iterator[tuple[str, type[dx.Model]]]:
    """Yield each record collection NSID with its resolved model class.

    Yields
    ------
    tuple
        A ``(collection_nsid, model_class)`` pair per record type whose model
        class resolves.
    """
    for collection in _RECORD_MODELS:
        model = _model_for(collection)
        if model is not None:
            yield collection, model
