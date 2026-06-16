"""Lexical-semantic knowledge-base connector backed by glazing.

Grounds lemmas, senses, frames, and rolesets against FrameNet, PropBank,
VerbNet, and WordNet through the glazing library's unified, type-safe
interface, with SemLink-style cross-reference resolution. Requires the
``lairs[lexical]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.integrations.kb import Candidate, Edge, Entity

__all__ = ["GlazingKB"]


class GlazingKB:
    """A lexical-semantic connector over glazing's four resources.

    Parameters
    ----------
    data_dir : str or None, optional
        The local glazing data directory; defaults to the glazing default.
    """

    name = "glazing"

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir

    def resolve(self, ref: str) -> Entity:
        """Resolve a lexical identifier to an entity.

        Parameters
        ----------
        ref : str
            The lexical identifier (for example a PropBank roleset
            ``give.01`` or a WordNet sense key).

        Returns
        -------
        lairs.integrations.kb.Entity
            The resolved lexical entity.

        Raises
        ------
        NotImplementedError
            Always, until the glazing connector lands.
        """
        raise NotImplementedError

    def search(
        self,
        text: str,
        *,
        lang: str | None = None,
        types: Sequence[str] | None = None,
    ) -> list[Candidate]:
        """Search the lexical resources for candidate entries.

        Parameters
        ----------
        text : str
            The lemma or surface form to search.
        lang : str or None, optional
            A language filter.
        types : collections.abc.Sequence of str or None, optional
            Resource or type constraints.

        Returns
        -------
        list of lairs.integrations.kb.Candidate
            The ranked candidates.

        Raises
        ------
        NotImplementedError
            Always, until the glazing connector lands.
        """
        raise NotImplementedError

    def neighbors(
        self,
        ref: str,
        *,
        rels: Sequence[str] | None = None,
    ) -> list[Edge]:
        """Expand a lexical entry's cross-references.

        Parameters
        ----------
        ref : str
            The lexical identifier to expand.
        rels : collections.abc.Sequence of str or None, optional
            Cross-reference relation filters.

        Returns
        -------
        list of lairs.integrations.kb.Edge
            The cross-reference edges (for example VerbNet links).

        Raises
        ------
        NotImplementedError
            Always, until the glazing connector lands.
        """
        raise NotImplementedError
