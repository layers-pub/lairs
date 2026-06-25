"""Unit tests for the lairs.atproto package surface."""

from __future__ import annotations

import lairs.atproto as mod


def test_all_lists_the_public_surface() -> None:
    assert set(mod.__all__) == {
        "AppviewClient",
        "BlobBytes",
        "BlobClient",
        "FirehoseEvent",
        "IdentityError",
        "IdentityResolution",
        "IdentityResolver",
        "PdsClient",
        "RecordDecodeFailure",
        "RecordEnvelope",
        "RecordNotFoundError",
        "RepoDescription",
        "RepoSubscriber",
        "Session",
        "SessionAuth",
        "SessionRenewalError",
        "SessionStore",
        "authed_client",
        "decode",
        "decode_all",
        "decode_repo_car",
        "describe_repo",
        "get_blob",
        "get_record",
        "get_repo",
        "list_records",
        "login",
        "resolve_did",
        "resolve_handle",
        "resolve_pds",
        "subscribe_repos",
    }


def test_every_export_is_importable() -> None:
    for name in mod.__all__:
        assert hasattr(mod, name)
