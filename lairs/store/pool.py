"""In-memory model pool with cross-reference resolution.

Maps AT-URIs to model instances and resolves cross-refs and back-refs, built
on top of didactic's :class:`didactic.api.ModelPool` and back-ref machinery.

The pool is the default surface for "load a corpus and work with it now". It
keeps every loaded record indexed by its AT-URI, resolves the AT-URI strings
that records carry as cross-references back to model instances, and answers
back-reference queries (which records point at a given target). Resolution
degrades gracefully: when a referenced AT-URI is not present in the pool the
string is preserved and ``resolve`` reports the absence rather than raising on
a missing target.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lairs._types import JsonValue

__all__ = ["ModelPool"]

# the prefix every AT-URI carries; used to recognise reference values when
# walking model fields generically.
_AT_URI_PREFIX = "at://"


def _dumped(model: dx.Model) -> JsonValue:
    """Return a fully-recursive JSON-shaped dump of a model.

    Uses :meth:`didactic.api.Model.model_dump_json` so nested models, tuples,
    and union members all normalise to plain JSON containers; the shallow
    :meth:`didactic.api.Model.model_dump` leaves tuple-of-model fields as model
    instances, which the generic AT-URI walk cannot descend into.

    Parameters
    ----------
    model : didactic.api.Model
        The model to dump.

    Returns
    -------
    JsonValue
        The model as nested JSON-shaped containers and scalars.
    """
    decoded: JsonValue = json.loads(model.model_dump_json())
    return decoded


def _iter_uri_values(value: JsonValue) -> Iterator[str]:
    """Yield every AT-URI string nested anywhere inside a dumped value.

    Walks a JSON-shaped value (the output of :meth:`didactic.api.Model.model_dump`)
    and yields each string that looks like an AT-URI, descending through nested
    lists and dictionaries so that references held inside embedded objects,
    tuples, and unions are all discovered.

    Parameters
    ----------
    value : JsonValue
        A JSON-shaped value produced by dumping a model.

    Yields
    ------
    str
        Each AT-URI-shaped string found in ``value``.
    """
    if isinstance(value, str):
        if value.startswith(_AT_URI_PREFIX):
            yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_uri_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_uri_values(nested)


class ModelPool:
    """An in-memory pool of records keyed by AT-URI.

    Wraps a :class:`didactic.api.ModelPool` (which indexes instances by their
    concrete class) with an AT-URI index, so records can be looked up by their
    canonical address and their cross-references resolved.

    Attributes
    ----------
    inner : didactic.api.ModelPool
        The underlying class-indexed pool that backs ``all_of``-style queries.
    """

    def __init__(self) -> None:
        self.inner = dx.ModelPool()
        # the AT-URI -> model index that makes this pool addressable.
        self._by_uri: dict[str, dx.Model] = {}

    def __len__(self) -> int:
        """Return the number of records held in the pool."""
        return len(self._by_uri)

    def __contains__(self, uri: str) -> bool:
        """Return ``True`` if ``uri`` is present in the pool."""
        return uri in self._by_uri

    def uris(self) -> list[str]:
        """Return the AT-URIs of every record in the pool.

        Returns
        -------
        list of str
            The AT-URIs, in insertion order.
        """
        return list(self._by_uri)

    def models(self) -> list[dx.Model]:
        """Return every model instance held in the pool.

        Returns
        -------
        list of didactic.api.Model
            The models, in insertion order.
        """
        return list(self._by_uri.values())

    def add(self, uri: str, model: dx.Model) -> None:
        """Add a model to the pool under its AT-URI.

        Adding the same AT-URI twice replaces the earlier instance in the
        AT-URI index. The model is also registered with the underlying
        class-indexed didactic pool.

        Parameters
        ----------
        uri : str
            The AT-URI of the record.
        model : didactic.api.Model
            The decoded model instance.
        """
        self._by_uri[uri] = model
        self.inner.add(model)

    def get(self, uri: str) -> dx.Model | None:
        """Return the model stored under ``uri``, or ``None`` if absent.

        Parameters
        ----------
        uri : str
            The AT-URI to look up.

        Returns
        -------
        didactic.api.Model or None
            The model, or ``None`` when ``uri`` is not in the pool.
        """
        return self._by_uri.get(uri)

    def resolve(self, ref: str) -> dx.Model | None:
        """Resolve a reference to its target model.

        A reference is an AT-URI string (the same form held by ``dx.Ref`` fields
        and free AT-URI fields). Resolution degrades gracefully: when the target
        is not loaded, ``None`` is returned and the caller may keep using the
        AT-URI string.

        Parameters
        ----------
        ref : str
            The AT-URI to resolve.

        Returns
        -------
        didactic.api.Model or None
            The target model, or ``None`` when it is not present in the pool.
        """
        return self._by_uri.get(ref)

    def refs_of(self, uri: str) -> list[str]:
        """Return the AT-URIs that the record at ``uri`` points at.

        Walks the dumped record generically, collecting every AT-URI-shaped
        string nested anywhere in its fields (including embedded objects, arrays,
        and union members). Duplicate targets are reported once, in first-seen
        order, and a record never lists itself.

        Parameters
        ----------
        uri : str
            The AT-URI of the referring record.

        Returns
        -------
        list of str
            The distinct AT-URIs referenced by the record, or an empty list when
            the record is absent.
        """
        model = self._by_uri.get(uri)
        if model is None:
            return []
        seen: dict[str, None] = {}
        for target in _iter_uri_values(_dumped(model)):
            if target != uri:
                seen.setdefault(target, None)
        return list(seen)

    def backrefs(self, target: str) -> list[dx.Model]:
        """List the models that reference a target.

        Scans every record in the pool and returns those that hold the target
        AT-URI anywhere in their fields. A target that is itself absent from the
        pool still resolves its back-references, so inbound links to a
        not-yet-loaded record are discoverable.

        Parameters
        ----------
        target : str
            The AT-URI of the referenced record.

        Returns
        -------
        list of didactic.api.Model
            The referring models, in insertion order.
        """
        referring: list[dx.Model] = []
        for uri, model in self._by_uri.items():
            if uri == target:
                continue
            if any(found == target for found in _iter_uri_values(_dumped(model))):
                referring.append(model)
        return referring

    def backref_uris(self, target: str) -> list[str]:
        """List the AT-URIs of the records that reference a target.

        Parameters
        ----------
        target : str
            The AT-URI of the referenced record.

        Returns
        -------
        list of str
            The AT-URIs of the referring records, in insertion order.
        """
        return [
            uri
            for uri, model in self._by_uri.items()
            if uri != target
            and any(found == target for found in _iter_uri_values(_dumped(model)))
        ]
