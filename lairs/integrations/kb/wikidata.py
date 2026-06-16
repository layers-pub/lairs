"""Wikidata knowledge-base connector.

Resolves and links against Wikidata, the hub other knowledge bases reconcile
to. Requires the ``lairs[wikidata]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.integrations.kb import Candidate, Edge, Entity

__all__ = ["WikidataKB"]


class WikidataKB:
    """A connector to Wikidata.

    Parameters
    ----------
    endpoint : str, optional
        The SPARQL or API endpoint to query.
    """

    name = "wikidata"

    def __init__(self, endpoint: str = "https://query.wikidata.org/sparql") -> None:
        self.endpoint = endpoint

    def resolve(self, ref: str) -> Entity:
        """Resolve a Wikidata identifier to an entity.

        Parameters
        ----------
        ref : str
            The Wikidata identifier or URI (for example ``Q42``).

        Returns
        -------
        lairs.integrations.kb.Entity
            The resolved entity.

        Raises
        ------
        NotImplementedError
            Always, until the Wikidata connector lands.
        """
        raise NotImplementedError

    def search(
        self,
        text: str,
        *,
        lang: str | None = None,
        types: Sequence[str] | None = None,
    ) -> list[Candidate]:
        """Search Wikidata for candidate entities.

        Parameters
        ----------
        text : str
            The surface text to link.
        lang : str or None, optional
            A language filter.
        types : collections.abc.Sequence of str or None, optional
            Type constraints.

        Returns
        -------
        list of lairs.integrations.kb.Candidate
            The ranked candidates.

        Raises
        ------
        NotImplementedError
            Always, until the Wikidata connector lands.
        """
        raise NotImplementedError

    def neighbors(
        self,
        ref: str,
        *,
        rels: Sequence[str] | None = None,
    ) -> list[Edge]:
        """Expand a Wikidata entity's neighbourhood.

        Parameters
        ----------
        ref : str
            The Wikidata identifier or URI to expand.
        rels : collections.abc.Sequence of str or None, optional
            Relation filters.

        Returns
        -------
        list of lairs.integrations.kb.Edge
            The neighbouring edges.

        Raises
        ------
        NotImplementedError
            Always, until the Wikidata connector lands.
        """
        raise NotImplementedError
