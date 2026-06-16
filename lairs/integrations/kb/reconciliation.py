"""Generic W3C/OpenRefine reconciliation knowledge-base connector.

A single reconciliation adapter speaks to any endpoint exposing the W3C /
OpenRefine reconciliation service API (Wikidata, VIAF, Getty, ORCID, ...), so
the entity-linking path is unified. Transport is :mod:`httpx`, a core
dependency, so this connector needs no optional extra.

The reconciliation service API is request/response over a single base URL. A
``queries`` POST returns ranked candidates per query; the optional data
extension, suggest, and preview services let ``resolve`` and ``neighbors``
recover an entity and its properties where the endpoint advertises them. A
connector that points at an endpoint missing a needed service fails with a
clear, actionable message rather than silently returning nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import httpx

from lairs._types import JsonValue  # noqa: TC001  (runtime: model construction)
from lairs.integrations.kb import Candidate, Edge, Entity

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

__all__ = ["ReconciliationError", "ReconciliationKB"]

DEFAULT_SEARCH_LIMIT = 10
"""The default number of candidates requested per reconciliation query."""


class ReconciliationError(RuntimeError):
    """A reconciliation endpoint did not support a requested capability.

    Raised when an endpoint omits a service (data extension, suggest, preview)
    that a method needs, so the caller sees an actionable message instead of an
    empty result.
    """


def _as_object(value: JsonValue) -> dict[str, JsonValue]:
    """Narrow a JSON value to an object, defaulting to an empty object.

    Parameters
    ----------
    value : JsonValue
        The JSON value to narrow.

    Returns
    -------
    dict
        The value as a JSON object, or an empty object if it is not one.
    """
    return value if isinstance(value, dict) else {}


def _as_array(value: JsonValue) -> list[JsonValue]:
    """Narrow a JSON value to an array, defaulting to an empty array.

    Parameters
    ----------
    value : JsonValue
        The JSON value to narrow.

    Returns
    -------
    list
        The value as a JSON array, or an empty array if it is not one.
    """
    return value if isinstance(value, list) else []


def _as_str(value: JsonValue) -> str:
    """Coerce a JSON value to a string, defaulting to the empty string.

    Parameters
    ----------
    value : JsonValue
        The JSON value to coerce.

    Returns
    -------
    str
        The value as a string, or the empty string if it is not one.
    """
    return value if isinstance(value, str) else ""


def _as_float(value: JsonValue) -> float:
    """Coerce a JSON value to a float, defaulting to zero.

    Parameters
    ----------
    value : JsonValue
        The JSON value to coerce.

    Returns
    -------
    float
        The value as a float, or ``0.0`` if it is not a number.
    """
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _candidate_from_result(result: dict[str, JsonValue]) -> Candidate:
    """Build a candidate from a reconciliation result object.

    Parameters
    ----------
    result : dict
        A single result object from a reconciliation ``queries`` response.

    Returns
    -------
    lairs.integrations.kb.Candidate
        The mapped candidate.
    """
    return Candidate(
        ref=_as_str(result.get("id")),
        label=_as_str(result.get("name")),
        score=_as_float(result.get("score")),
    )


def _proposed_properties(extend: dict[str, JsonValue]) -> list[JsonValue]:
    """Build the property list a data-extension request should request.

    The ``extend`` manifest block advertises the properties an endpoint can
    return via its ``propose_properties`` service; this maps them to the
    ``[{"id": ...}]`` shape the extend request expects.

    Parameters
    ----------
    extend : dict
        The ``extend`` block from the service manifest.

    Returns
    -------
    list
        The property descriptors for an extend request.
    """
    return [
        {"id": _as_str(_as_object(prop).get("id"))}
        for prop in _as_array(
            _as_object(extend.get("propose_properties")).get("properties"),
        )
    ]


class ReconciliationKB:
    """A connector to any reconciliation-service endpoint.

    Parameters
    ----------
    endpoint : str
        The reconciliation service base URL.
    client : httpx.Client or None, optional
        An injected HTTP client. When omitted, a private client is created and
        closed with this connector. Injecting a client lets a caller carry auth
        headers or a mock transport.
    limit : int, optional
        The default number of candidates requested per query.
    """

    name = "reconciliation"

    def __init__(
        self,
        endpoint: str,
        client: httpx.Client | None = None,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.limit = limit
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None
        self._entity_cache: dict[str, Entity] = {}
        self._search_cache: dict[
            tuple[str, str | None, tuple[str, ...]], list[Candidate]
        ] = {}

    def __enter__(self) -> Self:
        """Enter the connector as a context manager.

        Returns
        -------
        Self
            This connector.
        """
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Close the connector on context-manager exit.

        Parameters
        ----------
        _exc_type : type[BaseException] or None
            The exception type, if the block raised.
        _exc : BaseException or None
            The exception instance, if the block raised.
        _tb : types.TracebackType or None
            The traceback, if the block raised.
        """
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client if this connector owns it."""
        if self._owns_client:
            self._client.close()

    def _manifest(self) -> dict[str, JsonValue]:
        """Fetch the service manifest describing the endpoint's capabilities.

        Returns
        -------
        dict
            The reconciliation service manifest.

        Raises
        ------
        httpx.HTTPStatusError
            If the endpoint returns a non-success status.
        """
        response = self._client.get(self.endpoint)
        response.raise_for_status()
        return _as_object(response.json())

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
            A language filter, passed through to the endpoint when given.
        types : collections.abc.Sequence of str or None, optional
            Type constraints, passed through to the endpoint when given.

        Returns
        -------
        list of lairs.integrations.kb.Candidate
            The ranked candidates.

        Raises
        ------
        httpx.HTTPStatusError
            If the endpoint returns a non-success status.
        """
        key = (text, lang, tuple(types) if types is not None else ())
        cached = self._search_cache.get(key)
        if cached is not None:
            return list(cached)
        query: dict[str, JsonValue] = {"query": text, "limit": self.limit}
        if lang is not None:
            query["lang"] = lang
        if types:
            query["type"] = list(types)
        response = self._client.post(self.endpoint, json={"queries": {"q0": query}})
        response.raise_for_status()
        body = _as_object(response.json())
        block = _as_object(body.get("q0"))
        candidates = [
            _candidate_from_result(_as_object(result))
            for result in _as_array(block.get("result"))
        ]
        self._search_cache[key] = candidates
        return list(candidates)

    def resolve(self, ref: str) -> Entity:
        """Resolve an identifier to an entity via the reconciliation service.

        Resolution uses the optional data-extension service to recover the
        entity's label and any ``sameAs`` properties. The endpoint must
        advertise a ``extend`` service in its manifest.

        Parameters
        ----------
        ref : str
            The identifier to resolve.

        Returns
        -------
        lairs.integrations.kb.Entity
            The resolved entity.

        Raises
        ------
        ReconciliationError
            If the endpoint does not advertise a data-extension service.
        httpx.HTTPStatusError
            If the endpoint returns a non-success status.
        """
        cached = self._entity_cache.get(ref)
        if cached is not None:
            return cached
        manifest = self._manifest()
        extend = _as_object(manifest.get("extend"))
        if not extend:
            msg = (
                f"reconciliation endpoint {self.endpoint!r} advertises no data "
                "extension service, so resolve() cannot recover entity "
                "properties; use search() for candidates instead"
            )
            raise ReconciliationError(msg)
        entity = self._extend(ref, extend)
        self._entity_cache[ref] = entity
        return entity

    def _extend(self, ref: str, extend: dict[str, JsonValue]) -> Entity:
        """Resolve an entity through the data-extension service.

        Parameters
        ----------
        ref : str
            The identifier to extend.
        extend : dict
            The ``extend`` block from the service manifest.

        Returns
        -------
        lairs.integrations.kb.Entity
            The resolved entity.

        Raises
        ------
        httpx.HTTPStatusError
            If the endpoint returns a non-success status.
        """
        properties = _proposed_properties(extend)
        payload: dict[str, JsonValue] = {"ids": [ref], "properties": properties}
        response = self._client.post(self.endpoint, json={"extend": payload})
        response.raise_for_status()
        body = _as_object(response.json())
        rows = _as_object(body.get("rows"))
        row = _as_object(rows.get(ref))
        same_as: list[str] = []
        for cells in row.values():
            for cell in _as_array(cells):
                value = _as_object(cell).get("str") or _as_object(cell).get("id")
                if isinstance(value, str) and value:
                    same_as.append(value)
        label = self._preview_label(ref) if same_as else ""
        return Entity(
            ref=ref,
            label=label,
            same_as=tuple(dict.fromkeys(same_as)),
        )

    def _preview_label(self, ref: str) -> str:
        """Best-effort fetch of an entity's label via the suggest service.

        Parameters
        ----------
        ref : str
            The identifier whose label to fetch.

        Returns
        -------
        str
            The entity label, or the empty string if unavailable.
        """
        manifest = self._manifest()
        suggest = _as_object(_as_object(manifest.get("suggest")).get("entity"))
        service_url = _as_str(suggest.get("service_url"))
        service_path = _as_str(suggest.get("service_path"))
        if not service_url or not service_path:
            return ""
        response = self._client.get(
            f"{service_url}{service_path}",
            params={"prefix": ref},
        )
        if response.status_code != httpx.codes.OK:
            return ""
        result = _as_array(_as_object(response.json()).get("result"))
        if not result:
            return ""
        return _as_str(_as_object(result[0]).get("name"))

    def neighbors(
        self,
        ref: str,
        *,
        rels: Sequence[str] | None = None,
    ) -> list[Edge]:
        """Expand an entity's neighbourhood via the data-extension service.

        Each extended property whose cells carry entity identifiers becomes an
        edge ``ref -> property -> target``.

        Parameters
        ----------
        ref : str
            The identifier to expand.
        rels : collections.abc.Sequence of str or None, optional
            Relation filters; when given, only these property identifiers are
            requested.

        Returns
        -------
        list of lairs.integrations.kb.Edge
            The neighbouring edges.

        Raises
        ------
        ReconciliationError
            If the endpoint does not advertise a data-extension service.
        httpx.HTTPStatusError
            If the endpoint returns a non-success status.
        """
        manifest = self._manifest()
        extend = _as_object(manifest.get("extend"))
        if not extend:
            msg = (
                f"reconciliation endpoint {self.endpoint!r} advertises no data "
                "extension service, so neighbors() cannot expand the graph"
            )
            raise ReconciliationError(msg)
        if rels:
            properties: list[JsonValue] = [{"id": rel} for rel in rels]
        else:
            properties = _proposed_properties(extend)
        payload: dict[str, JsonValue] = {"ids": [ref], "properties": properties}
        response = self._client.post(self.endpoint, json={"extend": payload})
        response.raise_for_status()
        body = _as_object(response.json())
        row = _as_object(_as_object(body.get("rows")).get(ref))
        edges: list[Edge] = []
        for relation, cells in row.items():
            for cell in _as_array(cells):
                target = _as_object(cell).get("id")
                if isinstance(target, str) and target:
                    edges.append(Edge(source=ref, relation=relation, target=target))
        return edges
