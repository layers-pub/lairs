"""Unit tests for lairs.atproto._car."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import libipld
from multiformats import CID, multihash

from lairs.atproto import _car
from lairs.atproto._car import _cid_link, cid_to_base32, ipld_to_json

if TYPE_CHECKING:
    from lairs.atproto._car import IpldValue


def _cid_bytes(value: IpldValue) -> bytes:
    """Compute the raw CIDv1 dag-cbor bytes for a block value."""
    raw = libipld.encode_dag_cbor(value)
    return bytes(CID("base32", 1, "dag-cbor", multihash.digest(raw, "sha2-256")))


def test_exports() -> None:
    assert set(_car.__all__) == {"IpldValue", "cid_to_base32", "ipld_to_json"}


def test_cid_to_base32_matches_decode() -> None:
    raw = _cid_bytes({"text": "hi"})
    assert cid_to_base32(raw) == CID.decode(raw).encode("base32")
    assert cid_to_base32(raw).startswith("bafy")


def test_cid_link_round_trips_a_real_cid() -> None:
    raw = _cid_bytes({"text": "hi"})
    assert _cid_link(raw) == {"$link": cid_to_base32(raw)}


def test_cid_link_rejects_non_cid_bytes() -> None:
    assert _cid_link(b"plain bytes, not a cid") is None


def test_ipld_to_json_renders_byte_string_as_bytes_object() -> None:
    rendered = ipld_to_json(b"\x00\x01\x02")
    assert rendered == {"$bytes": base64.standard_b64encode(b"\x00\x01\x02").decode()}


def test_ipld_to_json_renders_cid_link() -> None:
    raw = _cid_bytes({"k": "v"})
    assert ipld_to_json(raw) == {"$link": cid_to_base32(raw)}


def test_ipld_to_json_recurses_into_containers() -> None:
    value: IpldValue = {"a": [1, "two", None], "b": {"c": True}}
    assert ipld_to_json(value) == {"a": [1, "two", None], "b": {"c": True}}
