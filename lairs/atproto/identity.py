"""Identity resolution: handle to DID and DID to PDS endpoint.

Resolves a handle to a DID (via DNS or ``.well-known``) and a DID to its PDS
endpoint (via the PLC directory or a ``did:web`` document), with caching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lairs._types import JsonValue

__all__ = ["resolve_did", "resolve_handle", "resolve_pds"]


def resolve_handle(handle: str) -> str:
    """Resolve a handle to a DID.

    Parameters
    ----------
    handle : str
        The ATProto handle (for example ``alice.bsky.social``).

    Returns
    -------
    str
        The resolved DID.

    Raises
    ------
    NotImplementedError
        Always, until the access layer lands.
    """
    raise NotImplementedError


def resolve_did(did: str) -> dict[str, JsonValue]:
    """Resolve a DID to its DID document.

    Parameters
    ----------
    did : str
        The DID to resolve.

    Returns
    -------
    dict
        The resolved DID document.

    Raises
    ------
    NotImplementedError
        Always, until the access layer lands.
    """
    raise NotImplementedError


def resolve_pds(did: str) -> str:
    """Resolve a DID to its PDS service endpoint.

    Parameters
    ----------
    did : str
        The DID to resolve.

    Returns
    -------
    str
        The PDS endpoint URL.

    Raises
    ------
    NotImplementedError
        Always, until the access layer lands.
    """
    raise NotImplementedError
