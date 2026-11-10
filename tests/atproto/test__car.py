"""Unit tests for lairs.atproto._car."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import libipld
import pytest
from multiformats import CID, multihash

from lairs.atproto import _car
from lairs.atproto._car import (
    CarFormatError,
    _cid_link,
    cid_to_base32,
    ipld_to_json,
    iter_car_sections,
    json_to_ipld,
    read_car_roots,
    record_cid,
)
from lairs.atproto.pds import RecordEnvelope

if TYPE_CHECKING:
    from pathlib import Path

    from lairs._types import JsonValue
    from lairs.atproto._car import IpldValue


def _cid_bytes(value: IpldValue) -> bytes:
    """Compute the raw CIDv1 dag-cbor bytes for a block value."""
    raw = libipld.encode_dag_cbor(value)
    return bytes(CID("base32", 1, "dag-cbor", multihash.digest(raw, "sha2-256")))


def test_exports() -> None:
    assert set(_car.__all__) == {
        "CarFormatError",
        "IpldValue",
        "cid_to_base32",
        "ipld_to_json",
        "iter_car_sections",
        "json_to_ipld",
        "read_car_roots",
        "record_cid",
    }


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


def test_ipld_to_json_converts_bytes_nested_in_lists() -> None:
    raw = _cid_bytes({"k": "v"})
    value: IpldValue = {"refs": [raw, b"\x00"], "n": 1.5}
    assert ipld_to_json(value) == {
        "refs": [
            {"$link": cid_to_base32(raw)},
            {"$bytes": base64.standard_b64encode(b"\x00").decode()},
        ],
        "n": 1.5,
    }


def test_json_to_ipld_inverts_ipld_to_json() -> None:
    raw = _cid_bytes({"k": "v"})
    value: IpldValue = {
        "link": raw,
        "blob": b"\x00\x01",
        "items": [raw, {"deep": [None, True, 3, "x"]}],
    }
    assert json_to_ipld(ipld_to_json(value)) == value


def test_json_to_ipld_leaves_non_link_objects_alone() -> None:
    # a multi-key object, a non-cid link string, and bad base64 are plain data.
    value: JsonValue = {
        "a": {"$link": "bafy", "other": 1},
        "b": {"$link": "not a cid"},
        "c": {"$bytes": "not base64!"},
        "d": {"$link": 3},
    }
    assert json_to_ipld(value) == value


def test_json_to_ipld_accepts_model_held_tuples() -> None:
    # a didactic model holds json arrays as tuples, so a value read back off an
    # envelope must convert like the list it was built from.
    envelope = RecordEnvelope(uri="at://x/y/z", cid="c", value={"a": ["b", ["c"]]})
    assert json_to_ipld(envelope.value) == {"a": ["b", ["c"]]}


def test_record_cid_reproduces_the_block_cid() -> None:
    link = _cid_bytes({"k": "v"})
    record: IpldValue = {
        "$type": "pub.layers.expression.expression",
        "text": "na\u00efve \u4e2d\u6587",
        "nothing": None,
        "empty": [],
        "big": 2**53 + 1,
        "ratio": 0.25,
        "ref": link,
    }
    assert record_cid(ipld_to_json(record)) == cid_to_base32(_cid_bytes(record))


def test_record_cid_changes_with_the_value() -> None:
    assert record_cid({"text": "a"}) != record_cid({"text": "b"})
    # a dropped null changes the block, so it changes the cid.
    assert record_cid({"text": "a", "x": None}) != record_cid({"text": "a"})


def _varint(value: int) -> bytes:
    """Encode an unsigned integer as an LEB128 varint for CAR framing."""
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def _car_bytes(roots: list[bytes], blocks: list[tuple[bytes, IpldValue]]) -> bytes:
    """Encode a CAR archive from root CIDs and ``(cid, value)`` blocks."""
    header = libipld.encode_dag_cbor({"roots": roots, "version": 1})
    car = bytearray(_varint(len(header)) + header)
    for cid, value in blocks:
        section = cid + libipld.encode_dag_cbor(value)
        car += _varint(len(section)) + section
    return bytes(car)


def test_iter_car_sections_yields_blocks_in_order(tmp_path: Path) -> None:
    # a block longer than 127 bytes exercises a multi-byte length prefix.
    values: list[IpldValue] = [{"n": 1}, {"text": "x" * 500}, {"n": 3}]
    blocks = [(_cid_bytes(value), value) for value in values]
    path = tmp_path / "repo.car"
    path.write_bytes(_car_bytes([blocks[0][0]], blocks))
    sections = list(iter_car_sections(path))
    assert [cid for cid, _ in sections] == [cid for cid, _ in blocks]
    assert [libipld.decode_dag_cbor(block) for _, block in sections] == values
    assert read_car_roots(path) == (blocks[0][0],)


def test_iter_car_sections_reads_cid_v0_blocks(tmp_path: Path) -> None:
    # a binary cidv0 is a bare 34-byte sha2-256 multihash.
    cid = multihash.digest(b"x", "sha2-256")
    path = tmp_path / "repo.car"
    path.write_bytes(_car_bytes([], [(cid, {"n": 1})]))
    assert [found for found, _ in iter_car_sections(path)] == [cid]
    assert read_car_roots(path) == ()


def test_car_reader_rejects_an_empty_archive(tmp_path: Path) -> None:
    path = tmp_path / "empty.car"
    path.write_bytes(b"")
    with pytest.raises(CarFormatError, match="empty"):
        read_car_roots(path)
    with pytest.raises(CarFormatError, match="empty"):
        list(iter_car_sections(path))


def test_car_reader_rejects_a_truncated_archive(tmp_path: Path) -> None:
    value: IpldValue = {"text": "x" * 500}
    car = _car_bytes([], [(_cid_bytes(value), value)])
    path = tmp_path / "cut.car"
    path.write_bytes(car[:-10])
    with pytest.raises(CarFormatError, match="ends inside a section"):
        list(iter_car_sections(path))
    # cut inside the two-byte length prefix of the block section.
    header_length = car[0] + 1
    path.write_bytes(car[: header_length + 1])
    with pytest.raises(CarFormatError, match="section length"):
        list(iter_car_sections(path))


def test_car_reader_rejects_a_malformed_header_and_cid(tmp_path: Path) -> None:
    path = tmp_path / "bad.car"
    path.write_bytes(_varint(3) + b"\xff\xff\xff")
    with pytest.raises(CarFormatError, match="DAG-CBOR"):
        read_car_roots(path)
    header = libipld.encode_dag_cbor({"roots": [], "version": 1})
    # a section that opens with neither a cidv0 nor a cidv1 marker.
    path.write_bytes(_varint(len(header)) + header + _varint(4) + b"\x09abc")
    with pytest.raises(CarFormatError, match="does not open with a CID"):
        list(iter_car_sections(path))
    # a cidv1 whose declared digest runs past the end of the section.
    path.write_bytes(_varint(len(header)) + header + _varint(5) + b"\x01\x71\x12\x20a")
    with pytest.raises(CarFormatError, match="truncated"):
        list(iter_car_sections(path))
    # an overlong varint where a section length belongs.
    path.write_bytes(_varint(len(header)) + header + b"\xff" * 11)
    with pytest.raises(CarFormatError, match="not a valid varint"):
        list(iter_car_sections(path))
