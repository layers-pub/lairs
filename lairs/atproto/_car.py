"""Shared IPLD and CAR decoding primitives for the ATProto wire format.

``libipld`` decodes DAG-CBOR blocks to plain Python structures, representing
both DAG-CBOR byte strings and CID links as ``bytes``. This module renders that
decoded form back to the DAG-JSON shape the XRPC record endpoints emit, so a
record recovered from a CAR archive (``getRepo``) or a commit stream
(``subscribeRepos``) validates against the generated models exactly as one
fetched over JSON does. Both consumers share these primitives.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from multiformats import CID

if TYPE_CHECKING:
    from lairs._types import JsonValue

__all__ = ["IpldValue", "cid_to_base32", "ipld_to_json"]

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
    if isinstance(value, bytes):
        link = _cid_link(value)
        if link is not None:
            return link
        return {"$bytes": base64.standard_b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {key: ipld_to_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [ipld_to_json(item) for item in value]
    return value
