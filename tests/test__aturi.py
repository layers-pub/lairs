"""Unit tests for lairs._aturi."""

from __future__ import annotations

from lairs import _aturi

_URI = "at://did:plc:me/pub.layers.media.media/abc"


def test_exports() -> None:
    assert set(_aturi.__all__) == {
        "authority_of",
        "is_tid",
        "is_valid_rkey",
        "nsid_of",
        "rkey_of",
    }


def test_rkey_of_extracts_the_record_key() -> None:
    assert _aturi.rkey_of(_URI) == "abc"
    assert _aturi.rkey_of("at://did:plc:me/pub.layers.media.media") == ""
    assert _aturi.rkey_of("") == ""


def test_is_valid_rkey_accepts_the_permitted_character_set() -> None:
    # alphanumerics plus period, dash, underscore, colon and tilde.
    assert _aturi.is_valid_rkey("ffff97dfcc791be9af7da146")
    assert _aturi.is_valid_rkey("self")
    assert _aturi.is_valid_rkey("3jzfcijpj2z2a")
    assert _aturi.is_valid_rkey("ewt.eng.ud")
    assert _aturi.is_valid_rkey("a-b_c~d")
    assert _aturi.is_valid_rkey("pre:fix")
    assert _aturi.is_valid_rkey("a" * 512)


def test_is_valid_rkey_rejects_out_of_range_and_reserved() -> None:
    assert not _aturi.is_valid_rkey("")
    assert not _aturi.is_valid_rkey("a" * 513)
    assert not _aturi.is_valid_rkey(".")
    assert not _aturi.is_valid_rkey("..")
    assert not _aturi.is_valid_rkey("has space")
    assert not _aturi.is_valid_rkey("has/slash")
    assert not _aturi.is_valid_rkey("percent%20")


def test_is_valid_rkey_rejects_a_trailing_newline() -> None:
    # a regex anchored with ``$`` rather than fullmatch would accept these,
    # letting the reserved values past the check.
    assert not _aturi.is_valid_rkey("abc\n")
    assert not _aturi.is_valid_rkey(".\n")
    assert not _aturi.is_valid_rkey("..\n")


def test_is_tid_matches_only_well_formed_tids() -> None:
    assert _aturi.is_tid("3jzfcijpj2z2a")
    # the live corpus's 24-char sha256 prefixes are not TIDs.
    assert not _aturi.is_tid("ffff97dfcc791be9af7da146")
    # wrong length, and a leading character outside the restricted set.
    assert not _aturi.is_tid("3jzfcijpj2z2")
    assert not _aturi.is_tid("zjzfcijpj2z2a")
    assert not _aturi.is_tid("3jzfcijpj2z2a\n")


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
