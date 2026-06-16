"""Unit tests for the lairs.atproto package surface."""

from __future__ import annotations

import lairs.atproto as mod


def test_all_lists_the_public_surface() -> None:
    assert set(mod.__all__) == {
        "AppviewClient",
        "BlobBytes",
        "BlobClient",
        "FirehoseEvent",
        "IdentityResolution",
        "IdentityResolver",
        "PdsClient",
        "RecordDecodeFailure",
        "RecordEnvelope",
        "RepoSubscriber",
        "decode",
        "decode_all",
        "get_blob",
        "get_record",
        "list_records",
        "resolve_did",
        "resolve_handle",
        "resolve_pds",
        "subscribe_repos",
        "upload_blob",
    }


def test_every_export_is_importable() -> None:
    for name in mod.__all__:
        assert hasattr(mod, name)
