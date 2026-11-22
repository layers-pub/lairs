"""Unit tests for lairs.store._pack."""

from __future__ import annotations

import base64
import json
import zlib
from typing import TYPE_CHECKING

import panproto
import pytest

from lairs.store import _pack
from lairs.store._pack import (
    PACK_ENCODING,
    PACK_LAYOUT_VERSION,
    decode_entries,
    decode_lines,
    encode_pack,
    entry_line,
    is_pack_key,
    pack_version,
    raw_text,
)

if TYPE_CHECKING:
    from lairs._types import JsonValue

_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"


def _envelope(text: str) -> dict[str, JsonValue]:
    _, envelope = encode_pack("pub.layers.expression.expression", [text])
    decoded: JsonValue = json.loads(envelope)
    assert isinstance(decoded, dict)
    return decoded


def test_exports() -> None:
    assert set(_pack.__all__) == {
        "PACK_ENCODING",
        "PACK_KEY_PREFIX",
        "PACK_LAYOUT_VERSION",
        "PackEnvelope",
        "decode_entries",
        "decode_lines",
        "encode_pack",
        "entry_line",
        "is_pack_key",
        "pack_version",
        "raw_text",
    }


def test_raw_text_keeps_order_nulls_and_text() -> None:
    value: dict[str, JsonValue] = {"z": None, "a": ["é", [], {}], "n": 2**70}
    assert raw_text(value) == '{"z":null,"a":["é",[],{}],"n":1180591620717411303424}'


def test_raw_text_rejects_non_finite_floats() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        raw_text({"x": float("inf")})


def test_entry_line_has_no_raw_newline() -> None:
    line = entry_line(_URI, '{\n  "text": "a\\nb"\n}')
    assert "\n" not in line
    assert json.loads(line) == [_URI, {"text": "a\nb"}]


def test_encode_pack_round_trips_entries_in_order() -> None:
    lines = [
        entry_line(_URI, '{"text":"one"}'),
        entry_line("at://x/c/2", "null"),
        entry_line(_URI, '{"text":"two"}'),
    ]
    key, envelope_text = encode_pack("pub.layers.expression.expression", lines)
    assert is_pack_key(key)
    assert key.startswith(f"lairs:pack:{PACK_LAYOUT_VERSION}:pub.layers.expression")
    assert pack_version(key) == PACK_LAYOUT_VERSION
    envelope: JsonValue = json.loads(envelope_text)
    assert isinstance(envelope, dict)
    assert envelope["count"] == 3
    assert envelope["encoding"] == PACK_ENCODING
    assert decode_lines(envelope, where="test") == lines
    assert decode_entries(envelope, where="test") == [
        (_URI, {"text": "one"}),
        ("at://x/c/2", None),
        (_URI, {"text": "two"}),
    ]


def test_an_empty_pack_decodes_to_nothing() -> None:
    _, envelope_text = encode_pack("c", [])
    envelope: JsonValue = json.loads(envelope_text)
    assert decode_lines(envelope, where="test") == []
    assert decode_entries(envelope, where="test") == []


def test_is_pack_key_does_not_match_at_uris() -> None:
    assert not is_pack_key(_URI)


def test_pack_version_rejects_unknown_and_missing_versions() -> None:
    with pytest.raises(panproto.VcsError, match="store layout 3"):
        pack_version("lairs:pack:3:c:0")
    with pytest.raises(panproto.VcsError, match="no layout version"):
        pack_version("lairs:pack:next:c:0")


def test_decode_rejects_malformed_envelopes() -> None:
    with pytest.raises(panproto.VcsError, match="not a pack envelope"):
        decode_entries([], where="test")
    envelope = _envelope(entry_line(_URI, "1"))
    envelope["layout"] = 3
    with pytest.raises(panproto.VcsError, match="declares store layout 3"):
        decode_entries(envelope, where="test")
    envelope = _envelope(entry_line(_URI, "1"))
    envelope["encoding"] = "zstd"
    with pytest.raises(panproto.VcsError, match="unsupported payload encoding"):
        decode_lines(envelope, where="test")


@pytest.mark.parametrize("line", ['["only-one"]', '[1, "value"]', '{"a": 1}'])
def test_decode_rejects_malformed_entries(line: str) -> None:
    envelope = _envelope(line)
    envelope["payload"] = base64.b64encode(zlib.compress(line.encode())).decode()
    with pytest.raises(panproto.VcsError, match="entry"):
        decode_entries(envelope, where="test")
