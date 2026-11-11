"""Shared IPLD and CAR decoding primitives for the ATProto wire format.

``libipld`` decodes DAG-CBOR blocks to plain Python structures, representing
both DAG-CBOR byte strings and CID links as ``bytes``. This module renders that
decoded form back to the DAG-JSON shape the XRPC record endpoints emit, so a
record recovered from a CAR archive (``getRepo``) or a commit stream
(``subscribeRepos``) validates against the generated models exactly as one
fetched over JSON does. Both consumers share these primitives.

A CAR archive is also readable incrementally. ``iter_car_sections`` walks the
sections of an archive stored on disk one block at a time, so a repository far
larger than memory can be decoded with a bounded footprint.

The rendering is invertible. ``json_to_ipld`` restores the decoded IPLD form
from the DAG-JSON shape, and ``record_cid`` re-encodes it to DAG-CBOR and
hashes it, so the CID a PDS reported for a record can be recomputed from the
record's JSON value alone.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import TYPE_CHECKING, BinaryIO

import libipld
from multiformats import CID

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from lairs._types import JsonValue

__all__ = [
    "CarFormatError",
    "IpldValue",
    "cid_to_base32",
    "ipld_to_json",
    "iter_car_sections",
    "json_to_ipld",
    "read_car_roots",
    "record_cid",
]

# the leading byte of a binary CIDv1.
_CID_V1 = 0x01
# the binary prefix of a CIDv1 over a DAG-CBOR block hashed with sha2-256: the
# version, the dag-cbor codec, the sha2-256 multihash code, and its length.
_DAG_CBOR_SHA256_PREFIX = b"\x01\x71\x12\x20"
# the two leading bytes of a binary CIDv0 (a bare sha2-256 multihash).
_CID_V0_PREFIX = b"\x12\x20"
# the byte length of a binary CIDv0.
_CID_V0_LENGTH = 34
# the continuation bit and payload mask of an unsigned LEB128 varint byte.
_VARINT_CONTINUE = 0x80
_VARINT_PAYLOAD = 0x7F
# the widest varint a CAR length prefix may occupy.
_MAX_VARINT_BYTES = 10

type IpldValue = (
    None | bool | int | float | str | bytes | list[IpldValue] | dict[str, IpldValue]
)
"""A recursive alias for a decoded IPLD value.

This is ``JsonValue`` widened to admit raw ``bytes``, which is how ``libipld``
represents both DAG-CBOR byte strings and CID links inside a decoded block. It
is the value type of the block store returned by ``libipld.decode_car``.
"""


def cid_to_base32(raw: bytes) -> str:
    """Render raw CID bytes as a base32 CID string.

    Parameters
    ----------
    raw : bytes
        The binary CID, as it appears inside a decoded block or commit op.

    Returns
    -------
    str
        The base32 CID string (the ``bafy...`` form the PDS reports).
    """
    if raw[:1] == bytes((_CID_V1,)):
        # a binary CIDv1 renders as the multibase prefix ``b`` followed by its
        # unpadded lowercase base32, which avoids a full multiformats decode on
        # the per-record path.
        return "b" + base64.b32encode(raw).decode("ascii").lower().rstrip("=")
    return CID.decode(raw).encode("base32")


def _cid_link(value: bytes) -> dict[str, JsonValue] | None:
    """Render a CID-link byte string as the DAG-JSON ``$link`` object.

    ``libipld`` decodes both DAG-CBOR byte strings and CID links to Python
    ``bytes``, so the two are distinguished here by attempting a CID round trip:
    bytes that decode to a CID and re-encode to exactly the same bytes are
    treated as a link. Genuine DAG-CBOR byte strings do not round-trip through
    the CID decoder, so they fall through to a ``$bytes`` rendering. ATProto
    record values carry binary payloads as blobs rather than inline byte
    strings, so a misclassification is not expected in practice.

    Parameters
    ----------
    value : bytes
        The candidate CID-link bytes.

    Returns
    -------
    dict of str to JsonValue or None
        The ``{"$link": cid}`` object if ``value`` is a CID, else ``None``.
    """
    try:
        cid = CID.decode(value)
    except ValueError, KeyError:
        return None
    if bytes(cid) != value:
        return None
    return {"$link": cid.encode("base32")}


def ipld_to_json(value: IpldValue) -> JsonValue:
    """Convert a decoded IPLD value to its DAG-JSON shape.

    CID links become ``{"$link": cid}`` objects and other byte strings become
    ``{"$bytes": base64}`` objects, matching the DAG-JSON encoding the XRPC
    record endpoints emit. Containers are converted recursively and scalars
    pass through unchanged.

    Parameters
    ----------
    value : IpldValue
        The decoded IPLD value.

    Returns
    -------
    JsonValue
        The JSON-shaped value.
    """
    # scalars dominate a record (most fields of a published record are null),
    # so each container tests its items inline and recurses only into nested
    # containers and byte strings.
    if isinstance(value, dict):
        return {
            key: item
            if item is None or isinstance(item, (str, int, float))
            else ipld_to_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            item
            if item is None or isinstance(item, (str, int, float))
            else ipld_to_json(item)
            for item in value
        ]
    if isinstance(value, bytes):
        link = _cid_link(value)
        if link is not None:
            return link
        return {"$bytes": base64.standard_b64encode(value).decode("ascii")}
    return value


def _link_bytes(value: dict[str, JsonValue]) -> bytes | None:
    """Return the bytes a single-key DAG-JSON ``$link``/``$bytes`` object names.

    Parameters
    ----------
    value : dict of str to JsonValue
        A JSON object that may be a DAG-JSON link or byte-string rendering.

    Returns
    -------
    bytes or None
        The binary CID of a ``{"$link": cid}`` object, the payload of a
        ``{"$bytes": base64}`` object, or ``None`` when ``value`` is neither.
    """
    if len(value) != 1:
        return None
    link = value.get("$link")
    if isinstance(link, str):
        try:
            return bytes(CID.decode(link))
        except ValueError, KeyError:
            return None
    payload = value.get("$bytes")
    if isinstance(payload, str):
        try:
            return base64.standard_b64decode(payload)
        except binascii.Error:
            return None
    return None


def json_to_ipld(value: JsonValue) -> IpldValue:
    """Convert a DAG-JSON-shaped value back to its decoded IPLD form.

    This inverts :func:`ipld_to_json`: a ``{"$link": cid}`` object becomes the
    binary CID and a ``{"$bytes": base64}`` object becomes the byte string, so
    the result encodes to the same DAG-CBOR block the value was decoded from.

    Parameters
    ----------
    value : JsonValue
        The JSON-shaped value.

    Returns
    -------
    IpldValue
        The IPLD value, with links and byte strings as ``bytes``.
    """
    if isinstance(value, dict):
        raw = _link_bytes(value)
        if raw is not None:
            return raw
        return {
            key: item
            if item is None or isinstance(item, (str, int, float))
            else json_to_ipld(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            item
            if item is None or isinstance(item, (str, int, float))
            else json_to_ipld(item)
            for item in value
        ]
    return value


def record_cid(value: JsonValue) -> str:
    """Compute the CID of a record from its DAG-JSON-shaped value.

    The value is restored to IPLD, encoded as canonical DAG-CBOR, and hashed
    with sha2-256, which is how a PDS derives the CID it reports for a record.
    A record value read back unchanged therefore reproduces its published CID,
    and any change to the value changes the result.

    Parameters
    ----------
    value : JsonValue
        The record value, in the shape the XRPC record endpoints emit
        (including its ``$type``).

    Returns
    -------
    str
        The base32 CIDv1 string of the record's DAG-CBOR block.
    """
    block = libipld.encode_dag_cbor(json_to_ipld(value))
    return cid_to_base32(_DAG_CBOR_SHA256_PREFIX + hashlib.sha256(block).digest())


class CarFormatError(ValueError):
    """A CAR archive is truncated or structurally malformed."""


def _read_varint(stream: BinaryIO) -> int | None:
    """Read one unsigned LEB128 varint, or ``None`` at a clean end of stream.

    Parameters
    ----------
    stream : typing.BinaryIO
        The binary stream positioned at a varint.

    Returns
    -------
    int or None
        The decoded value, or ``None`` when the stream is exhausted before the
        first byte.

    Raises
    ------
    CarFormatError
        When the stream ends inside a varint or the varint is overlong.
    """
    value = 0
    for index in range(_MAX_VARINT_BYTES):
        chunk = stream.read(1)
        if not chunk:
            if index == 0:
                return None
            msg = "CAR archive ends inside a section length"
            raise CarFormatError(msg)
        byte = chunk[0]
        value |= (byte & _VARINT_PAYLOAD) << (7 * index)
        if not byte & _VARINT_CONTINUE:
            return value
    msg = "CAR section length is not a valid varint"
    raise CarFormatError(msg)


def _read_section(stream: BinaryIO) -> bytes | None:
    """Read one length-prefixed CAR section, or ``None`` at end of stream.

    Parameters
    ----------
    stream : typing.BinaryIO
        The binary stream positioned at a section boundary.

    Returns
    -------
    bytes or None
        The section payload, or ``None`` when no section remains.

    Raises
    ------
    CarFormatError
        When the stream ends before the declared section length.
    """
    length = _read_varint(stream)
    if length is None:
        return None
    payload = stream.read(length)
    if len(payload) != length:
        msg = "CAR archive ends inside a section"
        raise CarFormatError(msg)
    return payload


def _varint_end(data: bytes, offset: int) -> int:
    """Return the offset just past the varint starting at ``offset``.

    Parameters
    ----------
    data : bytes
        The buffer holding the varint.
    offset : int
        The offset of the varint's first byte.

    Returns
    -------
    int
        The offset of the first byte after the varint.

    Raises
    ------
    CarFormatError
        When the buffer ends inside the varint.
    """
    for index in range(offset, min(offset + _MAX_VARINT_BYTES, len(data))):
        if not data[index] & _VARINT_CONTINUE:
            return index + 1
    msg = "CAR block CID is truncated"
    raise CarFormatError(msg)


def _decode_varint(data: bytes, offset: int) -> int:
    """Decode the unsigned LEB128 varint starting at ``offset``.

    Parameters
    ----------
    data : bytes
        The buffer holding the varint.
    offset : int
        The offset of the varint's first byte.

    Returns
    -------
    int
        The decoded value.
    """
    value = 0
    end = _varint_end(data, offset)
    for shift, index in enumerate(range(offset, end)):
        value |= (data[index] & _VARINT_PAYLOAD) << (7 * shift)
    return value


def _cid_length(section: bytes) -> int:
    """Return the byte length of the binary CID that opens a CAR section.

    A CIDv0 is a bare 34-byte sha2-256 multihash. A CIDv1 is a version varint,
    a codec varint, and a multihash (a code varint, a digest-length varint, and
    the digest).

    Parameters
    ----------
    section : bytes
        A CAR block section: the binary CID followed by the block bytes.

    Returns
    -------
    int
        The length of the leading CID.

    Raises
    ------
    CarFormatError
        When the section does not open with a well-formed CID.
    """
    if section[:2] == _CID_V0_PREFIX:
        return _CID_V0_LENGTH
    if section[:1] != bytes((_CID_V1,)):
        msg = "CAR block does not open with a CID"
        raise CarFormatError(msg)
    codec_end = _varint_end(section, 1)
    hash_code_end = _varint_end(section, codec_end)
    digest_start = _varint_end(section, hash_code_end)
    end = digest_start + _decode_varint(section, hash_code_end)
    if end > len(section):
        msg = "CAR block CID is truncated"
        raise CarFormatError(msg)
    return end


def read_car_roots(path: Path) -> tuple[bytes, ...]:
    """Return the root CIDs declared by the header of a CAR archive on disk.

    Parameters
    ----------
    path : pathlib.Path
        The CAR archive file.

    Returns
    -------
    tuple of bytes
        The binary root CIDs, in header order; empty when the header declares
        none.

    Raises
    ------
    CarFormatError
        When the archive has no readable header.
    """
    with path.open("rb") as stream:
        header_bytes = _read_section(stream)
    if header_bytes is None:
        msg = "CAR archive is empty"
        raise CarFormatError(msg)
    try:
        header = libipld.decode_dag_cbor(header_bytes)
    except ValueError as exc:
        msg = "CAR header is not valid DAG-CBOR"
        raise CarFormatError(msg) from exc
    roots = header.get("roots") if isinstance(header, dict) else None
    if not isinstance(roots, list):
        return ()
    return tuple(root for root in roots if isinstance(root, bytes))


def iter_car_sections(path: Path) -> Iterator[tuple[bytes, bytes]]:
    """Iterate the blocks of a CAR archive on disk without loading it whole.

    The archive is read one section at a time, so memory use is bounded by the
    largest single block rather than by the archive.

    Parameters
    ----------
    path : pathlib.Path
        The CAR archive file.

    Yields
    ------
    tuple of (bytes, bytes)
        Each block's binary CID and its undecoded DAG-CBOR bytes, in archive
        order.

    Raises
    ------
    CarFormatError
        When the archive is truncated or a section is malformed.
    """
    with path.open("rb") as stream:
        if _read_section(stream) is None:
            msg = "CAR archive is empty"
            raise CarFormatError(msg)
        while True:
            section = _read_section(stream)
            if section is None:
                return
            split = _cid_length(section)
            yield section[:split], section[split:]
