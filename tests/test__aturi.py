"""Unit tests for lairs._aturi."""

from __future__ import annotations

from lairs import _aturi

_URI = "at://did:plc:me/pub.layers.media.media/abc"


def test_exports() -> None:
    assert set(_aturi.__all__) == {"authority_of", "nsid_of"}


def test_authority_of_extracts_did() -> None:
    assert _aturi.authority_of(_URI) == "did:plc:me"


def test_authority_of_handles_non_at_uri() -> None:
    assert _aturi.authority_of("plain-string") == "plain-string"
    assert _aturi.authority_of("") == ""


def test_nsid_of_extracts_collection() -> None:
    assert _aturi.nsid_of(_URI) == "pub.layers.media.media"


def test_nsid_of_returns_empty_without_collection() -> None:
    assert _aturi.nsid_of("not-an-at-uri") == ""
    assert _aturi.nsid_of("at://did:plc:me") == ""
