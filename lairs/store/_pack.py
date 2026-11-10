"""The packed committed-data layout of the lairs record store.

The per-record layout stages one Panproto data set per AT-URI, which costs one
native staging call and one stored object per record. The packed layout stages
many records of one collection as a single data set instead: each record's
canonical JSON text becomes one line of a JSON-lines payload, the payload is
compressed with zlib and base64-encoded, and the result is committed as the one
record of a data set whose key names the layout version.

The payload is opaque to Panproto on purpose. Panproto's schema-bound data path
lifts every JSON node of a record into its instance graph, which costs about a
millisecond per few-kilobyte record on staging and again on reading, and it
coerces integers outside the signed 64-bit range to floats. A single compressed
string costs Panproto almost nothing to stage, hash, and decode, and the JSON
text inside it is stored exactly as written, so a raw record read back through
the packed layout keeps every key, null, list order, and number it was given.

A pack data set is recognized by its key, ``lairs:pack:<version>:<nsid>:<digest>``.
The version is the store layout version (:data:`PACK_LAYOUT_VERSION`); a reader
that meets a pack written under a version it does not know raises rather than
guessing at the payload.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import TYPE_CHECKING

import didactic.api as dx
import panproto

if TYPE_CHECKING:
    from lairs._types import JsonValue

__all__ = [
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
]

PACK_LAYOUT_VERSION = 2
"""The store layout version that the packed data sets are written under.

Layout 1 is the per-record layout, which carries no marker; layout 2 adds the
packed data sets and the journaled working-tree index.
"""

PACK_KEY_PREFIX = "lairs:pack:"
"""The data-set key prefix that marks a committed data set as a pack."""

PACK_ENCODING = "jsonl+zlib+base64"
"""The payload encoding of a layout-2 pack."""

# the zlib level trades a little staging time for a much smaller payload; 6 is
# zlib's own default and compresses annotation JSON about tenfold.
_ZLIB_LEVEL = 6
# the number of hex digits of the payload digest carried in the data-set key.
_KEY_DIGEST_HEX = 16
# a payload entry is the pair ``[uri, value]``.
_ENTRY_ARITY = 2


class PackEnvelope(dx.Model):
    """The one committed record of a packed data set.

    Attributes
    ----------
    layout : int
        The store layout version the pack was written under.
    collection : str
        The collection NSID shared by every record in the pack.
    count : int
        The number of entries in the payload.
    encoding : str
        The payload encoding, :data:`PACK_ENCODING` for layout 2.
    payload : str
        The base64 text of the zlib-compressed JSON-lines payload. Each line is
        a two-element JSON array ``[uri, value]``.
    """

    layout: int = dx.field(description="store layout version of the pack")
    collection: str = dx.field(description="collection NSID of every entry")
    count: int = dx.field(description="number of entries in the payload")
    encoding: str = dx.field(description="payload encoding")
    payload: str = dx.field(description="base64 zlib JSON-lines payload")


def raw_text(value: JsonValue) -> str:
    """Return the compact JSON text of a raw record value, losslessly.

    Keys keep their order, nulls and empty containers are kept, and non-ASCII
    text is written as itself. Non-finite floats are rejected because they have
    no JSON form.

    Parameters
    ----------
    value : JsonValue
        The record value.

    Returns
    -------
    str
        The compact JSON text of ``value``.

    Raises
    ------
    ValueError
        If ``value`` holds a non-finite float.
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def entry_line(uri: str, text: str) -> str:
    """Return the payload line for one record.

    Parameters
    ----------
    uri : str
        The record's AT-URI.
    text : str
        The record value's JSON text.

    Returns
    -------
    str
        The line ``[uri, value]`` with no raw newline in it.
    """
    if "\n" in text or "\r" in text:
        # json text only carries raw line breaks as insignificant whitespace,
        # so a re-dump removes them without changing the value.
        text = json.dumps(
            json.loads(text),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return f"[{json.dumps(uri, ensure_ascii=False)},{text}]"


def encode_pack(collection: str, lines: list[str]) -> tuple[str, str]:
    """Encode payload lines as a pack envelope.

    Parameters
    ----------
    collection : str
        The collection NSID shared by the lines.
    lines : list of str
        The payload lines, as built by :func:`entry_line`.

    Returns
    -------
    tuple of (str, str)
        The data-set key and the envelope's JSON text.
    """
    payload = zlib.compress("\n".join(lines).encode("utf-8"), _ZLIB_LEVEL)
    encoded = base64.b64encode(payload).decode("ascii")
    digest = hashlib.sha256(payload).hexdigest()[:_KEY_DIGEST_HEX]
    envelope = PackEnvelope(
        layout=PACK_LAYOUT_VERSION,
        collection=collection,
        count=len(lines),
        encoding=PACK_ENCODING,
        payload=encoded,
    )
    key = f"{PACK_KEY_PREFIX}{PACK_LAYOUT_VERSION}:{collection}:{digest}"
    return key, envelope.model_dump_json()


def is_pack_key(key: str) -> bool:
    """Return whether a data-set key names a pack.

    Parameters
    ----------
    key : str
        A committed data-set key.

    Returns
    -------
    bool
        Whether ``key`` carries the pack prefix.
    """
    return key.startswith(PACK_KEY_PREFIX)


def pack_version(key: str) -> int:
    """Return the layout version a pack key names, checking it is supported.

    Parameters
    ----------
    key : str
        A pack data-set key.

    Returns
    -------
    int
        The layout version, :data:`PACK_LAYOUT_VERSION`.

    Raises
    ------
    panproto.VcsError
        If the key carries no version or a version this lairs cannot read.
    """
    version_text = key.removeprefix(PACK_KEY_PREFIX).split(":", 1)[0]
    if not version_text.isdigit():
        msg = f"committed pack {key!r} carries no layout version"
        raise panproto.VcsError(msg)
    version = int(version_text)
    if version != PACK_LAYOUT_VERSION:
        msg = (
            f"committed pack {key!r} uses store layout {version}, but this "
            f"lairs reads layout {PACK_LAYOUT_VERSION} at most; upgrade lairs "
            "to read it"
        )
        raise panproto.VcsError(msg)
    return version


def _payload_text(envelope: JsonValue, *, where: str) -> str:
    """Return the decompressed payload text of a decoded envelope."""
    if not isinstance(envelope, dict):
        msg = f"{where} is not a pack envelope object"
        raise panproto.VcsError(msg)
    layout = envelope.get("layout")
    encoding = envelope.get("encoding")
    payload = envelope.get("payload")
    if layout != PACK_LAYOUT_VERSION:
        msg = (
            f"{where} declares store layout {layout!r}; this lairs reads layout "
            f"{PACK_LAYOUT_VERSION}"
        )
        raise panproto.VcsError(msg)
    if encoding != PACK_ENCODING or not isinstance(payload, str):
        msg = f"{where} has unsupported payload encoding {encoding!r}"
        raise panproto.VcsError(msg)
    return zlib.decompress(base64.b64decode(payload)).decode("utf-8")


def decode_lines(envelope: JsonValue, *, where: str) -> list[str]:
    """Return the payload lines of a decoded envelope.

    Parameters
    ----------
    envelope : JsonValue
        The envelope, as a decoded JSON object.
    where : str
        A description of the pack's location for error messages.

    Returns
    -------
    list of str
        One JSON line ``[uri, value]`` per entry.

    Raises
    ------
    panproto.VcsError
        If the envelope is malformed or of an unknown version or encoding.
    """
    text = _payload_text(envelope, where=where)
    return text.split("\n") if text else []


def decode_entries(
    envelope: JsonValue,
    *,
    where: str,
) -> list[tuple[str, JsonValue]]:
    """Return the ``(uri, value)`` entries of a decoded envelope, in order.

    Parameters
    ----------
    envelope : JsonValue
        The envelope, as a decoded JSON object.
    where : str
        A description of the pack's location for error messages.

    Returns
    -------
    list of (str, JsonValue)
        The entries in staging order; a later entry for a URI supersedes an
        earlier one.

    Raises
    ------
    panproto.VcsError
        If the envelope or any entry is malformed.
    """
    text = _payload_text(envelope, where=where)
    if not text:
        return []
    # lines hold no raw newline, so joining them with commas is one json array
    # and a single parse is much faster than one parse per line.
    decoded: JsonValue = json.loads("[" + text.replace("\n", ",") + "]")
    entries: list[tuple[str, JsonValue]] = []
    if not isinstance(decoded, list):  # pragma: no cover - the join is a list
        msg = f"{where} payload is not a list"
        raise panproto.VcsError(msg)
    for item in decoded:
        if not (isinstance(item, list) and len(item) == _ENTRY_ARITY):
            msg = f"{where} holds a malformed entry"
            raise panproto.VcsError(msg)
        uri, value = item
        if not isinstance(uri, str):
            msg = f"{where} holds an entry whose URI is not a string"
            raise panproto.VcsError(msg)
        entries.append((uri, value))
    return entries
