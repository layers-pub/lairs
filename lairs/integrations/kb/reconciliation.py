"""Generic W3C/OpenRefine reconciliation knowledge-base connector.

A single reconciliation adapter speaks to any endpoint exposing the W3C /
OpenRefine reconciliation service API (Wikidata, VIAF, Getty, ORCID, ...), so
the entity-linking path is unified. Requires the ``lairs[reconciliation]``
extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.integrations.kb import Candidate, Edge, Entity

__all__ = ["ReconciliationKB"]


class ReconciliationKB:
    """A connector to any reconciliation-service endpoint.

    Parameters
    ----------
    endpoint : str
        The reconciliation service base URL.
    """

    name = "reconciliation"

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def resolve(self, ref: str) -> Entity:
        """Resolve an identifier to an entity via the reconciliation service.

        Parameters
        ----------
        ref : str
            The identifier or URI to resolve.

        Returns
        -------
        lairs.integrations.kb.Entity
            The resolved entity.

        Raises
        ------
        NotImplementedError
            Always, until the reconciliation connector lands.
        """
        raise NotImplementedError

    def search(
        self,
        text: str,
        *,
        lang: str | None = None,
        types: Sequence[str] | None = None,
    ) -> list[Candidate]:
        """Reconcile surface text to candidate entities.

        Parameters
        ----------
        text : str
            The surface text to reconcile.
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
            Always, until the reconciliation connector lands.
        """
        raise NotImplementedError

    def neighbors(
        self,
        ref: str,
        *,
        rels: Sequence[str] | None = None,
    ) -> list[Edge]:
        """Expand an entity's neighbourhood, if the endpoint supports it.

        Parameters
        ----------
        ref : str
            The identifier or URI to expand.
        rels : collections.abc.Sequence of str or None, optional
            Relation filters.

        Returns
        -------
        list of lairs.integrations.kb.Edge
            The neighbouring edges.

        Raises
        ------
        NotImplementedError
            Always, until the reconciliation connector lands.
        """
        raise NotImplementedError
