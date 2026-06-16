"""Unit and integration tests for lairs.atproto.identity."""

from __future__ import annotations

import pytest

from lairs.atproto import identity


def test_exports() -> None:
    assert set(identity.__all__) == {"resolve_did", "resolve_handle", "resolve_pds"}


def test_resolve_handle_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        identity.resolve_handle("alice.test")


def test_resolve_did_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        identity.resolve_did("did:plc:abc")


def test_resolve_pds_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        identity.resolve_pds("did:plc:abc")


@pytest.mark.integration
def test_resolve_handle_live() -> None:
    # exercises real DNS/well-known resolution when opted in; skips otherwise.
    try:
        did = identity.resolve_handle("bsky.app")
    except NotImplementedError:
        pytest.skip("identity resolution not implemented yet")
    assert did.startswith("did:")
