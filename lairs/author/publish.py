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
are chunked to a PDS batch limit; when a batch call fails it is retried one
record at a time as ``putRecord`` upserts at each write's own rkey (so a record
already committed by the partially-applied batch is upserted rather than
duplicated), and reported back as a per-record result set
(created / updated / deleted / failed with reasons).

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
from lairs.atproto.pds import PdsClient, decode
from lairs.author.changelog import build_entry, diff_record
from lairs.records import changelog as changelog_models
from lairs.records.blobref import BlobRef

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from datetime import datetime
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

_EMPTY_COLLECTION_STATUSES = frozenset({400, 404})
"""The PDS statuses treated as an empty (unknown) collection, not a failure."""

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
    # tier 3: annotations over expressions and tokens; graph nodes; standalone
    # corpora and resource containers. these cite only tier 0-2 records.
    "pub.layers.annotation.annotationLayer": 3,
    "pub.layers.graph.graphNode": 3,
    "pub.layers.alignment.alignment": 3,
    "pub.layers.corpus.corpus": 3,
    "pub.layers.resource.collection": 3,
    "pub.layers.resource.template": 3,
    # tier 4: records over tier-3 records. cluster sets cite annotations; edges
    # cite nodes; resource members cite their container or template.
    "pub.layers.annotation.clusterSet": 4,
    "pub.layers.graph.graphEdge": 4,
    "pub.layers.corpus.membership": 4,
    "pub.layers.resource.entry": 4,
    "pub.layers.resource.filling": 4,
    "pub.layers.resource.collectionMembership": 4,
    "pub.layers.resource.templateComposition": 4,
    "pub.layers.judgment.experimentDef": 4,
    "pub.layers.judgment.judgmentSet": 4,
    "pub.layers.changelog.entry": 4,
    # tier 5: records over tier-4 records. edge sets cite edges; agreement
    # reports cite judgment sets.
    "pub.layers.graph.graphEdgeSet": 5,
    "pub.layers.judgment.agreementReport": 5,
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
        The outcome: ``created``, ``updated``, ``deleted``, or ``failed``.
    cid : str or None, optional
        The content identifier returned by the PDS, when the write succeeded.
    reason : str or None, optional
        A human-readable reason for a failed write.
    """

    uri: str = dx.field(description="AT-URI of the record")
    status: str = dx.field(description="created, updated, deleted, or failed")
    cid: str | None = dx.field(
        default=None,
        description="content identifier returned by the PDS, when successful",
    )
    reason: str | None = dx.field(
        default=None,
        description="reason for a failed write",
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
        if not isinstance(blob, dict):
            msg = "uploadBlob response did not contain a 'blob' reference object"
            raise WriteError(msg)
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
        idempotent ``putRecord`` upserts at each write's own rkey when the batch
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
            parsed = self._post(_APPLY_WRITES_NSID, body)
        except WriteError:
            return self._retry_chunk(chunk)
        raw_results = parsed.get("results")
        cids = _apply_writes_result_cids(raw_results, len(chunk))
        return tuple(
            WriteResult(
                uri=op.uri,
                status="created" if op.action == "create" else op.action + "d",
                cid=cids[index],
            )
            for index, op in enumerate(chunk)
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


def _apply_writes_result_cids(
    raw_results: JsonValue,
    count: int,
) -> tuple[str | None, ...]:
    """Extract per-write CIDs from an ``applyWrites`` ``results`` array.

    The PDS returns a ``results`` array aligned with the input writes; create
    and update results carry a ``cid``, delete results do not. A short, absent,
    or malformed array yields ``None`` for the missing positions so the caller
    always gets exactly ``count`` entries.

    Parameters
    ----------
    raw_results : JsonValue
        The ``results`` value from the ``applyWrites`` response.
    count : int
        The number of writes in the batch.

    Returns
    -------
    tuple of (str or None)
        The committed CID per write position, or ``None`` where unavailable.
    """
    results = raw_results if isinstance(raw_results, list) else []
    cids: list[str | None] = []
    for index in range(count):
        entry = results[index] if index < len(results) else None
        cid = entry.get("cid") if isinstance(entry, dict) else None
        cids.append(cid if isinstance(cid, str) else None)
    return tuple(cids)


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


def _blob_to_wire(blob: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Convert a lairs blob reference map to the ATProto blob wire form.

    The generated :class:`~lairs.records.blobref.BlobRef` dumps as
    ``{"cid": ..., "mime_type": ..., "size": ...}``; a PDS stores and addresses
    a blob as ``{"$type": "blob", "ref": {"$link": cid}, "mimeType": ...,
    "size": ...}``. Converting to the wire form lets both the write value and
    the locally computed CID match what the PDS stores.

    Parameters
    ----------
    blob : collections.abc.Mapping
        The lairs blob reference map.

    Returns
    -------
    dict
        The ATProto blob object in its JSON wire form.
    """
    cid = blob.get("cid")
    wire: dict[str, JsonValue] = {
        "$type": "blob",
        "ref": {"$link": cid},
    }
    mime_type = blob.get("mime_type")
    if mime_type is not None:
        wire["mimeType"] = mime_type
    size = blob.get("size")
    if size is not None:
        wire["size"] = size
    return wire


def _blobs_to_wire(value: JsonValue, model: type[dx.Model] | None) -> JsonValue:
    """Rewrite every blob field of a record value to the ATProto wire form.

    The walk is model-driven: a field is converted only when the generated
    model declares it (or its array element, or a nested model field) as a
    :class:`~lairs.records.blobref.BlobRef`, so non-blob maps are never
    misidentified. The value is left unchanged when no model is available.

    Parameters
    ----------
    value : JsonValue
        The record value in its lairs JSON form.
    model : type of didactic.api.Model or None
        The record's generated model, or ``None`` when unresolved.

    Returns
    -------
    JsonValue
        The value with every blob field in ATProto wire form.
    """
    if model is None or not isinstance(value, dict):
        return value
    converted = dict(value)
    for spec in model.__field_specs__.values():
        key = spec.alias if spec.alias is not None else spec.name
        if key not in converted:
            continue
        converted[key] = _convert_field(converted[key], spec.annotation)
    return converted


def _convert_field(field_value: JsonValue, annotation: object) -> JsonValue:
    """Convert one field value per its annotated type.

    Parameters
    ----------
    field_value : JsonValue
        The field's JSON value.
    annotation : object
        The field's type annotation (possibly a union or a list element type).

    Returns
    -------
    JsonValue
        The converted value: blob maps become wire blobs and nested models
        recurse; everything else is returned unchanged.
    """
    members = getattr(annotation, "__args__", (annotation,))
    for member in members:
        if member is BlobRef:
            if isinstance(field_value, dict):
                return _blob_to_wire(field_value)
            return field_value
        if isinstance(member, type) and issubclass(member, dx.Model):
            return _blobs_to_wire(field_value, member)
        origin = getattr(member, "__origin__", None)
        if origin in (list, tuple) and isinstance(field_value, list):
            args = [arg for arg in getattr(member, "__args__", ()) if arg is not ...]
            element = args[0] if args else None
            return [_convert_field(item, element) for item in field_value]
    return field_value


def _value_with_type(value: JsonValue, collection: str) -> JsonValue:
    """Prepare a record value for writing and CID computation.

    Two normalisations are applied. First, the collection NSID is injected as
    ``$type`` (ATProto records embed it; the generated model dump does not).
    Second, every blob field is rewritten from the lairs
    :class:`~lairs.records.blobref.BlobRef` form to the ATProto blob wire form
    so a blob-bearing record both writes correctly and content-addresses the
    way the PDS does (making a re-publish of an unchanged blob record a no-op).

    Parameters
    ----------
    value : JsonValue
        The record value.
    collection : str
        The collection NSID.

    Returns
    -------
    JsonValue
        The value with ``$type`` set and blob fields in ATProto wire form.
    """
    if not isinstance(value, dict):
        return value
    typed = _blobs_to_wire(value, _model_for(collection))
    if not isinstance(typed, dict):
        return typed
    typed = dict(typed)
    typed.setdefault("$type", collection)
    return typed


type _DagCborValue = (
    str
    | int
    | float
    | bool
    | None
    | bytes
    | list[_DagCborValue]
    | dict[str, _DagCborValue]
)
"""A DAG-CBOR encoding input: a JSON value extended with raw ``bytes`` leaves.

This is the shape ``libipld.encode_dag_cbor`` consumes once cid-link maps have
been rewritten to raw CID bytes. It is a :data:`JsonValue` plus ``bytes``, which
DAG-CBOR encodes as a CID link (CBOR tag 42).
"""


def _dag_cbor_links(value: JsonValue) -> _DagCborValue:
    """Rewrite cid-link maps so DAG-CBOR encodes them as CID links.

    In the JSON form of a record, a CID link (including the ``ref`` of every
    blob) is the map ``{"$link": "<cid>"}``. ``libipld`` encodes that map as an
    ordinary string map, but a PDS stores the link as a DAG-CBOR CID link (CBOR
    tag 42), which ``libipld`` emits only when the value is the raw CID bytes.
    This walk replaces each ``{"$link": "<cid>"}`` with ``bytes(CID)`` so the
    locally computed CID matches the PDS-reported CID for blob-bearing records.

    Parameters
    ----------
    value : JsonValue
        The record value in its JSON form.

    Returns
    -------
    _DagCborValue
        The value with every cid-link map replaced by its raw CID bytes.
    """
    if isinstance(value, dict):
        link = value.get("$link")
        if len(value) == 1 and isinstance(link, str):
            return bytes(CID.decode(link))
        return {key: _dag_cbor_links(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dag_cbor_links(item) for item in value]
    return value


def _record_cid(value: JsonValue) -> str:
    """Return the ATProto record CID for a value.

    The CID is a CIDv1 over the DAG-CBOR encoding of the value with a sha-256
    multihash and the dag-cbor codec, computed the way a PDS computes the CID it
    reports for a stored record. Cid-link maps (such as every blob ``ref``) are
    first rewritten to their DAG-CBOR CID-link form so a blob-bearing record's
    locally computed CID matches the PDS-reported CID. Computing it the same way
    lets the publish diff detect an unchanged record by CID equality.

    Parameters
    ----------
    value : JsonValue
        The record value, including its ``$type``.

    Returns
    -------
    str
        The record's CIDv1 string.
    """
    encoded = libipld.encode_dag_cbor(_dag_cbor_links(value))
    digest = multihash.digest(encoded, "sha2-256")
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

    Raises
    ------
    WriteError
        If a collection fails to enumerate with a status other than an empty
        or unknown collection (for example a 5xx), so a degraded PDS aborts the
        diff rather than producing a wrong plan.
    httpx.HTTPError
        If a transport-level failure (connection or timeout) occurs.
    """
    cids: dict[str, str] = {}
    with PdsClient(endpoint, client) as pds_client:
        for collection in _RECORD_MODELS:
            try:
                for envelope in pds_client.list_records(repo, collection):
                    cids[envelope.uri] = envelope.cid
            except httpx.HTTPStatusError as exc:
                # an unknown or empty collection may 400/404; treat it as empty.
                # any other status (notably a 5xx) means the PDS could not
                # report the collection, so re-raise rather than silently
                # dropping records that are genuinely present.
                if exc.response.status_code in _EMPTY_COLLECTION_STATUSES:
                    continue
                msg = (
                    f"listing {collection} on {repo} failed with status "
                    f"{exc.response.status_code}"
                )
                raise WriteError(msg) from exc
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


_CHANGELOG_NSID = "pub.layers.changelog.entry"
"""The collection NSID of a changelog entry record."""


def _first_parent(repo: Repository, revision: str) -> str | None:
    """Return the first-parent commit of a revision, or ``None`` at the root.

    Parameters
    ----------
    repo : Repository
        The local repository.
    revision : str
        The revision (ref expression) whose parent is sought.

    Returns
    -------
    str or None
        The first parent commit id, or ``None`` when the revision is the initial
        commit.
    """
    target = repo.resolve(revision)
    for entry in repo.log():
        if str(entry.get("id")) == target:
            parents = entry.get("parents")
            if isinstance(parents, list) and parents:
                return str(parents[0])
            return None
    return None


def _latest_published_versions(
    repo: str,
    *,
    endpoint: str,
    client: httpx.Client | None = None,
) -> dict[str, changelog_models.SemanticVersion]:
    """Return the latest published semantic version per subject on a PDS.

    The target repository's ``pub.layers.changelog.entry`` collection is
    enumerated and each entry decoded; for each subject the version from the
    entry with the most recent ``createdAt`` wins, so a later publish bumps from
    the version last published rather than from local history, keeping versions
    monotonic across runs. An unknown or empty collection yields an empty
    mapping.

    Parameters
    ----------
    repo : str
        The target repository DID.
    endpoint : str
        The base URL of the PDS.
    client : httpx.Client or None, optional
        An injected HTTP client; a private one is created when omitted.

    Returns
    -------
    dict of str to lairs.records.changelog.SemanticVersion
        A mapping from subject AT-URI to its latest published version.

    Raises
    ------
    WriteError
        If the collection fails to enumerate with a status other than an empty
        or unknown collection.
    """
    with PdsClient(endpoint, client) as pds_client:
        try:
            envelopes = list(pds_client.list_records(repo, _CHANGELOG_NSID))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _EMPTY_COLLECTION_STATUSES:
                return {}
            msg = (
                f"listing {_CHANGELOG_NSID} on {repo} failed with status "
                f"{exc.response.status_code}"
            )
            raise WriteError(msg) from exc
    versions: dict[str, changelog_models.SemanticVersion] = {}
    latest: dict[str, datetime] = {}
    for envelope in envelopes:
        try:
            # decode drops the wire ``$type`` the generated model does not
            # declare, so a real PDS entry validates rather than being skipped.
            entry = decode(envelope, changelog_models.Entry)
        except dx.ValidationError:
            continue
        version = entry.version
        if version is None:
            continue
        if entry.subject not in latest or entry.createdAt > latest[entry.subject]:
            latest[entry.subject] = entry.createdAt
            versions[entry.subject] = version
    return versions


def _augment_with_changelog(  # noqa: PLR0913  (the hook threads publish's knobs)
    repo: Repository,
    revision: str,
    plan: PublishPlan,
    *,
    to: str,
    base: str | None,
    endpoint: str | None,
    client: httpx.Client | None,
) -> PublishPlan:
    """Augment a publish plan with a changelog entry per changed record.

    For each record the plan creates, updates, or deletes (excluding changelog
    entries themselves), a ``pub.layers.changelog.entry`` is generated from the
    field-level diff of the record between the base revision and ``revision`` and
    merged into the plan's creates. The base defaults to the revision's first
    parent. The prior version per subject is read from the most recently
    published entry on the PDS, so versions stay monotonic across runs. A subject
    whose content is unchanged contributes no entry, keeping a re-publish
    idempotent.

    Parameters
    ----------
    repo : Repository
        The local repository holding the revisions.
    revision : str
        The revision being published.
    plan : PublishPlan
        The data-record plan to augment.
    to : str
        The target repository DID.
    base : str or None
        The base revision for the content diff, or ``None`` to use the
        revision's first parent.
    endpoint : str or None
        The base URL of the PDS, used to read prior versions; prior versions are
        empty when omitted.
    client : httpx.Client or None
        An injected HTTP client for the prior-version read.

    Returns
    -------
    PublishPlan
        The plan with changelog-entry creates merged in, or the original plan
        when there is nothing to record.
    """
    subjects = sorted(
        {
            op.uri
            for op in (*plan.creates, *plan.updates, *plan.deletes)
            if collection_of(op.uri) != _CHANGELOG_NSID
        },
    )
    if not subjects:
        return plan
    base_revision = base if base is not None else _first_parent(repo, revision)
    old_state = repo.content_at(base_revision) if base_revision is not None else {}
    new_state = repo.content_at(revision)
    prev_versions = (
        _latest_published_versions(to, endpoint=endpoint, client=client)
        if endpoint is not None
        else {}
    )
    changelog_ops: list[WriteOp] = []
    for uri in subjects:
        field_diff = diff_record(old_state.get(uri), new_state.get(uri))
        if field_diff.record_change == "unchanged" and not field_diff.changes:
            continue
        entry = build_entry(
            subject=uri,
            subject_collection=collection_of(uri),
            field_diff=field_diff,
            previous_version=prev_versions.get(uri),
        )
        version = entry.version
        if version is None:
            continue
        raw = json.loads(entry.model_dump_json())
        value = _value_with_type(raw, _CHANGELOG_NSID)
        rkey = f"{_rkey_of(uri)}.{version.major}.{version.minor}.{version.patch}"
        changelog_ops.append(
            WriteOp(
                action="create",
                collection=_CHANGELOG_NSID,
                rkey=rkey,
                uri=f"at://{to}/{_CHANGELOG_NSID}/{rkey}",
                value=value,
            ),
        )
    if not changelog_ops:
        return plan
    return PublishPlan(
        repo=plan.repo,
        revision=plan.revision,
        creates=order_writes((*plan.creates, *changelog_ops)),
        updates=plan.updates,
        deletes=plan.deletes,
    )


def publish(  # noqa: PLR0913  (the publish workflow needs these distinct knobs)
    repo: Repository,
    revision: str,
    *,
    to: str,
    endpoint: str | None = None,
    client: httpx.Client | None = None,
    dry_run: bool = False,
    changelog: bool = False,
    changelog_base: str | None = None,
) -> PublishPlan:
    """Publish a Repository revision to a PDS as the minimal write set.

    The target revision is diffed against what is already on the PDS (by AT-URI
    and CID) and the minimal ``applyWrites`` plan is emitted. When ``dry_run``
    is ``True`` the plan is returned without sending any writes. Otherwise the
    plan's writes are applied in dependency order (via
    :meth:`PublishPlan.ordered_writes`) and the computed plan is returned for
    inspection.

    When ``changelog`` is ``True`` the plan is augmented with one
    ``pub.layers.changelog.entry`` per changed record, generated from the
    field-level diff between ``changelog_base`` (or the revision's first parent)
    and ``revision`` and versioned monotonically from the most recently published
    entry on the PDS. The default ``changelog=False`` leaves the plan unchanged.

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
    changelog : bool, optional
        If ``True``, augment the plan with a changelog entry per changed record.
    changelog_base : str or None, optional
        The base revision for the changelog field diff; defaults to the
        revision's first parent. Ignored unless ``changelog`` is ``True``.

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
    if changelog:
        plan = _augment_with_changelog(
            repo,
            revision,
            plan,
            to=to,
            base=changelog_base,
            endpoint=endpoint,
            client=client,
        )
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
