"""Optional appview XRPC query client.

A thin client over the Layers query API used for discovery and cross-ref
resolution without walking PDSes. lairs works with the appview off or on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lairs._types import JsonValue

__all__ = ["AppviewClient"]


class AppviewClient:
    """A thin XRPC client over the Layers appview query API.

    Parameters
    ----------
    endpoint : str
        The base URL of the appview XRPC endpoint.
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def query(
        self,
        nsid: str,
        params: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        """Issue an XRPC query against the appview.

        Parameters
        ----------
        nsid : str
            The query method NSID (for example ``corpus.listCorpora``).
        params : dict
            The query parameters.

        Returns
        -------
        dict
            The decoded XRPC response body.

        Raises
        ------
        NotImplementedError
            Always, until the access layer lands.
        """
        raise NotImplementedError
