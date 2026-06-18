"""AT-URI parsing helpers shared across lairs.

Small, dependency-free helpers for pulling the authority and collection segments
out of an ``at://`` URI. Centralised here so the discovery, CLI, and data layers
parse AT-URIs the same way.
"""

from __future__ import annotations

__all__ = ["authority_of", "nsid_of"]

_AT_URI_PREFIX = "at://"
"""The scheme prefix every AT-URI carries."""

_MIN_PARTS_WITH_COLLECTION = 2
"""The number of path segments an AT-URI needs to carry a collection NSID."""


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
