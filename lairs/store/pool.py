"""In-memory model pool with cross-reference resolution.

Maps AT-URIs to model instances and resolves cross-refs and back-refs, built
on didactic's pool and back-ref machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import didactic.api as dx

__all__ = ["ModelPool"]


class ModelPool:
    """An in-memory pool of records keyed by AT-URI."""

    def add(self, uri: str, model: dx.Model) -> None:
        """Add a model to the pool under its AT-URI.

        Parameters
        ----------
        uri : str
            The AT-URI of the record.
        model : didactic.Model
            The decoded model instance.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError

    def resolve(self, ref: str) -> dx.Model:
        """Resolve a reference to its target model.

        Parameters
        ----------
        ref : str
            The AT-URI to resolve.

        Returns
        -------
        didactic.Model
            The target model, if present.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError

    def backrefs(self, target: str) -> list[dx.Model]:
        """List the models that reference a target.

        Parameters
        ----------
        target : str
            The AT-URI of the referenced record.

        Returns
        -------
        list of didactic.Model
            The referring models.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError
