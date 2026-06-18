"""ATProto access layer.

Thin facade over the ATProto transport for identity resolution, direct-PDS
record fetch, blob fetch, the optional appview query client, and the deferred
firehose consumer. The transport is built on ``httpx`` rather than the
``atproto`` SDK; lairs owns the Layers-specific layer (NSID handling, decode to
generated models, cross-ref resolution) and keeps the client read-only, with an
injectable session for later auth and writes.
"""

from __future__ import annotations

from lairs.atproto.appview import AppviewClient
from lairs.atproto.auth import (
    Session,
    SessionAuth,
    SessionStore,
    authed_client,
    login,
)
from lairs.atproto.blobs import BlobBytes, BlobClient, get_blob, upload_blob
from lairs.atproto.firehose import FirehoseEvent, RepoSubscriber, subscribe_repos
from lairs.atproto.identity import (
    IdentityResolution,
    IdentityResolver,
    resolve_did,
    resolve_handle,
    resolve_pds,
)
from lairs.atproto.pds import (
    PdsClient,
    RecordDecodeFailure,
    RecordEnvelope,
    RepoDescription,
    decode,
    decode_all,
    describe_repo,
    get_record,
    list_records,
)

__all__ = [
    "AppviewClient",
    "BlobBytes",
    "BlobClient",
    "FirehoseEvent",
    "IdentityResolution",
    "IdentityResolver",
    "PdsClient",
    "RecordDecodeFailure",
    "RecordEnvelope",
    "RepoDescription",
    "RepoSubscriber",
    "Session",
    "SessionAuth",
    "SessionStore",
    "authed_client",
    "decode",
    "decode_all",
    "describe_repo",
    "get_blob",
    "get_record",
    "list_records",
    "login",
    "resolve_did",
    "resolve_handle",
    "resolve_pds",
    "subscribe_repos",
    "upload_blob",
]
