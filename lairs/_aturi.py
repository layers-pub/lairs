"""AT-URI parsing helpers shared across lairs.

Small, dependency-free helpers for pulling the authority and collection segments
out of an ``at://`` URI. Centralised here so the discovery, CLI, and data layers
parse AT-URIs the same way.

These helpers are positional string splitters, not validators. They assume a
well-formed ``at://authority/collection/rkey`` URI and return an empty string
for a missing segment; they do not check the ``at://`` scheme or the authority
shape, so malformed input yields a best-effort segment rather than an error.
Callers that need validation must do it before calling.
"""

from __future__ import annotations

import re

__all__ = ["authority_of", "is_tid", "is_valid_rkey", "nsid_of", "rkey_of"]

_AT_URI_PREFIX = "at://"
"""The scheme prefix every AT-URI carries."""

_MIN_PARTS_WITH_COLLECTION = 2
"""The number of path segments an AT-URI needs to carry a collection NSID."""

_MIN_PARTS_WITH_RKEY = 3
"""The number of path segments an AT-URI needs to carry a record key."""

# the atproto record-key syntax: alphanumerics plus period, dash, underscore,
# colon and tilde, 1 to 512 characters. fullmatch rather than match with a
# trailing ``$``, because in python ``$`` also matches before a final newline,
# which would let "." and ".." past the reserved-value check below.
_RKEY_PATTERN = re.compile(r"[a-zA-Z0-9._:~-]{1,512}")

_RESERVED_RKEYS = frozenset({".", ".."})
"""Record keys the syntax explicitly forbids."""

# a TID is 13 characters of base32-sortable, and its leading character is
# further restricted because the high bit of the 64-bit value is always clear.
_TID_PATTERN = re.compile(r"[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}")


def is_valid_rkey(rkey: str) -> bool:
    """Return whether a string is a syntactically valid atproto record key.

    Checks the record-key syntax only: the permitted character set, the 1 to 512
    length bound, and the two reserved values. It does not check agreement with
    a lexicon's declared ``key`` type, which is a separate question.

    Note that the record-key specification permits a colon while the repository
    specification's path character set omits one, so a key containing ``:`` is
    accepted here yet may not be a legal repository path. lairs therefore never
    mints a key containing a colon, though it will read one.

    Parameters
    ----------
    rkey : str
        The candidate record key.

    Returns
    -------
    bool
        Whether ``rkey`` satisfies the record-key syntax.
    """
    if rkey in _RESERVED_RKEYS:
        return False
    return _RKEY_PATTERN.fullmatch(rkey) is not None


def is_tid(rkey: str) -> bool:
    """Return whether a record key is a well-formed TID.

    Parameters
    ----------
    rkey : str
        The candidate record key.

    Returns
    -------
    bool
        Whether ``rkey`` is 13 characters of base32-sortable with a leading
        character in the restricted set.
    """
    return _TID_PATTERN.fullmatch(rkey) is not None


def rkey_of(uri: str) -> str:
    """Return the record-key segment of an AT-URI.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The record key, or an empty string when the URI carries none.
    """
    body = uri.removeprefix(_AT_URI_PREFIX)
    parts = body.split("/")
    if len(parts) >= _MIN_PARTS_WITH_RKEY:
        return parts[2]
    return ""


def authority_of(uri: str) -> str:
    """Return the authority (DID or handle) segment of an AT-URI.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The authority segment, or an empty string when ``uri`` is empty.
    """
    body = uri.removeprefix(_AT_URI_PREFIX)
    return body.split("/", 1)[0] if body else ""


def nsid_of(uri: str) -> str:
    """Return the collection NSID segment of an AT-URI.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The collection NSID, or an empty string when the URI has no collection.
    """
    body = uri.removeprefix(_AT_URI_PREFIX)
    parts = body.split("/")
    if len(parts) >= _MIN_PARTS_WITH_COLLECTION:
        return parts[1]
    return ""
