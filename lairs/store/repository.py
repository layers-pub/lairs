"""didactic Repository wrapper: the on-disk schematic version control.

Wraps ``didactic.vcs.Repository`` so a corpus snapshot is a commit and a named
dataset version is a tag, giving reproducibility, provenance, and cheap
diffing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from lairs._types import JsonValue

__all__ = ["Repository"]


class Repository:
    """A wrapper over a didactic Repository for Layers records.

    Parameters
    ----------
    path : pathlib.Path
        The on-disk location of the repository.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def commit(self, message: str) -> str:
        """Commit the staged records as a schema snapshot.

        Parameters
        ----------
        message : str
            The commit message.

        Returns
        -------
        str
            The new revision identifier.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError

    def tag(self, name: str, *, revision: str | None = None) -> None:
        """Tag a revision as a named dataset version.

        Parameters
        ----------
        name : str
            The tag name.
        revision : str or None, optional
            The revision to tag; defaults to the current head.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError

    def diff(self, base: str, head: str) -> dict[str, JsonValue]:
        """Diff two revisions.

        Parameters
        ----------
        base : str
            The base revision.
        head : str
            The head revision.

        Returns
        -------
        dict
            The schema-aware diff between the revisions.

        Raises
        ------
        NotImplementedError
            Always, until the store layer lands.
        """
        raise NotImplementedError
