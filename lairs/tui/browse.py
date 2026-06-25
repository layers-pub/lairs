"""The data layer behind the Browse tab: typed record access over a Repository.

A :class:`RepoBrowser` opens a local :class:`lairs.store.repository.Repository`
(the output of ``lairs pull``), enumerates the record types present with counts,
loads any record into its typed model, and answers the related-record queries the
type-aware renderers need (the type definitions of an ontology, the response sets
of an experiment, the entries of a lexicon, and so on).

:func:`materialize_repo` flattens the whole repository into the Parquet views the
Query tab queries: a normalized ``expressions`` and exploded ``annotations``
view, plus one raw table per remaining record type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx
from panproto import PanprotoError

from lairs.store.arrow import (
    annotations_table,
    expressions_table,
    materialize,
    records_to_table,
)
from lairs.store.repository import Repository, Workspace
from lairs.tui.registry import RECORD_MODELS

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from lairs._types import JsonValue

__all__ = ["BrowseError", "RepoBrowser", "materialize_repo"]

_EXPRESSION_NSID = "pub.layers.expression.expression"
_LAYER_NSID = "pub.layers.annotation.annotationLayer"


class BrowseError(Exception):
    """Raised when a repository cannot be opened for browsing."""


def _nsid_of(uri: str) -> str:
    """Return the collection NSID segment of an AT-URI."""
    body = uri.removeprefix("at://")
    parts = body.split("/")
    minimum_parts = 2
    return parts[1] if len(parts) >= minimum_parts else ""


class RepoBrowser:
    """Typed, cached access to the records of a local Repository.

    Parameters
    ----------
    repo : lairs.store.repository.Repository
        The repository whose records to browse.
    """

    def __init__(self, repo: Repository) -> None:
        self._repo = repo
        self._by_nsid = Workspace(repo).by_nsid()
        self._cache: dict[str, list[tuple[str, dx.Model]]] = {}
        self._raw_cache: dict[str, list[tuple[str, Mapping[str, JsonValue]]]] = {}

    @classmethod
    def open(cls, path: Path) -> RepoBrowser:
        """Open a repository directory for browsing.

        Parameters
        ----------
        path : pathlib.Path
            A directory holding a populated Repository.

        Returns
        -------
        RepoBrowser
            A browser over the repository.

        Raises
        ------
        BrowseError
            When the directory is not a readable repository.
        """
        try:
            repo = Repository.open(path)
        except (OSError, ValueError, PanprotoError) as error:
            msg = f"could not open repository at {path}: {error}"
            raise BrowseError(msg) from error
        return cls(repo)

    @property
    def repo(self) -> Repository:
        """Return the backing repository."""
        return self._repo

    def type_counts(self) -> list[tuple[str, int]]:
        """Return the record types present with their counts.

        Known record types come first in the registry's namespace order; any
        unrecognized collection follows, sorted, so nothing is hidden.

        Returns
        -------
        list of (str, int)
            Pairs of collection NSID and record count.
        """
        known = [
            (nsid, len(self._by_nsid[nsid]))
            for nsid in RECORD_MODELS
            if nsid in self._by_nsid
        ]
        extras = sorted(
            (nsid, len(uris))
            for nsid, uris in self._by_nsid.items()
            if nsid not in RECORD_MODELS
        )
        return known + extras

    def uris_of(self, nsid: str) -> list[str]:
        """Return the AT-URIs of every record of a collection."""
        return list(self._by_nsid.get(nsid, ()))

    def load(self, uri: str) -> dx.Model | None:
        """Load a record into its typed model, or ``None`` when unknown."""
        model_cls = RECORD_MODELS.get(_nsid_of(uri))
        if model_cls is None:
            return None
        loaded = self._repo.load(uri, model_cls)
        return loaded if isinstance(loaded, dx.Model) else None

    def load_raw(self, uri: str) -> JsonValue | None:
        """Load a record's raw JSON value (for the generic renderer)."""
        return self._repo.load_raw(uri)

    def records_of(self, nsid: str) -> list[tuple[str, dx.Model]]:
        """Return ``(uri, model)`` for every decodable record of a collection.

        Results are cached per collection, so repeated related-record queries
        over the same type are cheap.
        """
        if nsid not in self._cache:
            decoded: list[tuple[str, dx.Model]] = []
            for uri in self.uris_of(nsid):
                model = self.load(uri)
                if model is not None:
                    decoded.append((uri, model))
            self._cache[nsid] = decoded
        return self._cache[nsid]

    def records_raw(
        self,
        nsid: str,
    ) -> list[tuple[str, Mapping[str, JsonValue]]]:
        """Return ``(uri, raw-json)`` for every record of a collection.

        The raw JSON form is what the type-aware renderers read, so they work
        over concrete ``JsonValue`` containers rather than dynamic attributes.
        Results are cached per collection.
        """
        if nsid not in self._raw_cache:
            decoded: list[tuple[str, Mapping[str, JsonValue]]] = []
            for uri in self.uris_of(nsid):
                raw = self._repo.load_raw(uri)
                if isinstance(raw, dict):
                    decoded.append((uri, raw))
            self._raw_cache[nsid] = decoded
        return self._raw_cache[nsid]

    def related_raw(
        self,
        nsid: str,
        field: str,
        value: JsonValue,
    ) -> list[tuple[str, Mapping[str, JsonValue]]]:
        """Return the records of a collection whose ``field`` equals ``value``.

        Parameters
        ----------
        nsid : str
            The collection to scan (for example the type-definition collection).
        field : str
            The field to match (for example ``ontologyRef``).
        value : lairs._types.JsonValue
            The value the field must equal (for example an ontology AT-URI).

        Returns
        -------
        list of (str, collections.abc.Mapping)
            The matching records as raw JSON.
        """
        return [
            (uri, raw) for uri, raw in self.records_raw(nsid) if raw.get(field) == value
        ]


def materialize_repo(repo: Repository, out_dir: Path) -> list[Path]:
    """Flatten a whole repository into the Query tab's Parquet views.

    Writes a normalized ``expressions`` view and an exploded ``annotations``
    view (so the concordance and CQL modes work), plus one raw table per
    remaining record type (so SQL reaches ontologies, resources, experiments,
    graphs, and the rest).

    Parameters
    ----------
    repo : lairs.store.repository.Repository
        The repository to flatten.
    out_dir : pathlib.Path
        The output directory for the Parquet views.

    Returns
    -------
    list of pathlib.Path
        The written view files.
    """
    browser = RepoBrowser(repo)
    views = {}
    expressions = [model for _, model in browser.records_of(_EXPRESSION_NSID)]
    if expressions:
        views["expressions"] = expressions_table(expressions)
    layers = browser.records_of(_LAYER_NSID)
    if layers:
        views["annotations"] = annotations_table(layers)
    for nsid, count in browser.type_counts():
        if nsid in (_EXPRESSION_NSID, _LAYER_NSID) or count == 0:
            continue
        models = [model for _, model in browser.records_of(nsid)]
        if models:
            views[nsid.replace(".", "_")] = records_to_table(models)
    return materialize(repo, out_dir, views=views)
