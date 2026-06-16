"""Wikidata knowledge-base connector.

Resolves and links against Wikidata, the hub other knowledge bases reconcile
to. The default transport is the public Wikidata REST, action, and SPARQL
endpoints over :mod:`httpx` (a core dependency), so no extra is required for the
common path. The ``lairs[wikidata]`` extra (``qwikidata`` / ``SPARQLWrapper``)
is supported for callers who prefer those clients and is imported lazily, never
at module import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import httpx

from lairs._types import JsonValue  # noqa: TC001  (runtime: model construction)
from lairs.integrations.kb import Candidate, Edge, Entity

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

__all__ = ["WikidataKB"]

DEFAULT_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
"""The public Wikidata Query Service SPARQL endpoint."""

DEFAULT_API_ENDPOINT = "https://www.wikidata.org/w/api.php"
"""The public Wikidata action API endpoint (search)."""

DEFAULT_ENTITY_ENDPOINT = "https://www.wikidata.org/wiki/Special:EntityData"
"""The public Wikidata linked-data entity endpoint (resolve)."""

DEFAULT_SEARCH_LIMIT = 10
"""The default number of candidates requested from the search API."""

DEFAULT_NEIGHBOR_LIMIT = 100
"""The default number of edges requested from the SPARQL endpoint."""

_WD_ENTITY_PREFIX = "http://www.wikidata.org/entity/"
"""The URI prefix for Wikidata entities in SPARQL bindings."""

_WD_PROP_PREFIX = "http://www.wikidata.org/prop/direct/"
"""The URI prefix for Wikidata direct properties in SPARQL bindings."""


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


def _qid(ref: str) -> str:
    """Normalise a Wikidata reference to a bare QID.

    Accepts a bare QID (``Q42``) or any full or prefixed entity URI and returns
    the trailing identifier.

    Parameters
    ----------
    ref : str
        The Wikidata identifier or URI.

    Returns
    -------
    str
        The bare QID.
    """
    if ref.startswith(_WD_ENTITY_PREFIX):
        return ref.removeprefix(_WD_ENTITY_PREFIX)
    if ref.startswith("wd:"):
        return ref.removeprefix("wd:")
    return ref.rsplit("/", 1)[-1]


class WikidataKB:
    """A connector to Wikidata over its public REST, action, and SPARQL APIs.

    Parameters
    ----------
    endpoint : str, optional
        The SPARQL endpoint used by :meth:`neighbors`.
    api_endpoint : str, optional
        The action API endpoint used by :meth:`search`.
    entity_endpoint : str, optional
        The linked-data entity endpoint used by :meth:`resolve`.
    lang : str, optional
        The default label language.
    client : httpx.Client or None, optional
        An injected HTTP client. When omitted, a private client is created and
        closed with this connector; injecting one lets tests supply a mock
        transport.
    """

    name = "wikidata"

    def __init__(
        self,
        endpoint: str = DEFAULT_SPARQL_ENDPOINT,
        *,
        api_endpoint: str = DEFAULT_API_ENDPOINT,
        entity_endpoint: str = DEFAULT_ENTITY_ENDPOINT,
        lang: str = "en",
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.api_endpoint = api_endpoint
        self.entity_endpoint = entity_endpoint
        self.lang = lang
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None
        self._entity_cache: dict[str, Entity] = {}
        self._search_cache: dict[tuple[str, str], list[Candidate]] = {}

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
        httpx.HTTPStatusError
            If the entity endpoint returns a non-success status.
        """
        qid = _qid(ref)
        cached = self._entity_cache.get(qid)
        if cached is not None:
            return cached
        response = self._client.get(f"{self.entity_endpoint}/{qid}.json")
        response.raise_for_status()
        entity = self._entity_from_data(qid, _as_object(response.json()))
        self._entity_cache[qid] = entity
        return entity

    def _entity_from_data(self, qid: str, body: dict[str, JsonValue]) -> Entity:
        """Map a Wikidata EntityData JSON body to an entity.

        Parameters
        ----------
        qid : str
            The entity QID.
        body : dict
            The EntityData JSON body.

        Returns
        -------
        lairs.integrations.kb.Entity
            The mapped entity.
        """
        entity = _as_object(_as_object(body.get("entities")).get(qid))
        label = self._term(entity.get("labels"))
        description = self._term(entity.get("descriptions")) or None
        aliases = tuple(
            _as_str(_as_object(alias).get("value"))
            for alias in _as_array(_as_object(entity.get("aliases")).get(self.lang))
            if _as_str(_as_object(alias).get("value"))
        )
        claims = _as_object(entity.get("claims"))
        types = self._claim_targets(claims.get("P31"))
        same_as = self._sitelink_urls(entity.get("sitelinks"))
        return Entity(
            ref=qid,
            label=label,
            aliases=aliases,
            types=types,
            description=description,
            same_as=same_as,
        )

    def _term(self, terms: JsonValue) -> str:
        """Extract a label or description in the configured language.

        Parameters
        ----------
        terms : JsonValue
            A Wikidata term map (labels or descriptions).

        Returns
        -------
        str
            The term value, or the empty string if absent.
        """
        return _as_str(_as_object(_as_object(terms).get(self.lang)).get("value"))

    def _claim_targets(self, claim: JsonValue) -> tuple[str, ...]:
        """Extract the entity-id targets of a claim group.

        Parameters
        ----------
        claim : JsonValue
            A claim group (the value of one property key).

        Returns
        -------
        tuple of str
            The target QIDs, in order.
        """
        targets: list[str] = []
        for statement in _as_array(claim):
            snak = _as_object(_as_object(_as_object(statement).get("mainsnak")))
            datavalue = _as_object(snak.get("datavalue"))
            target = _as_object(datavalue.get("value")).get("id")
            if isinstance(target, str) and target:
                targets.append(target)
        return tuple(targets)

    def _sitelink_urls(self, sitelinks: JsonValue) -> tuple[str, ...]:
        """Extract cross-reference URLs from an entity's sitelinks.

        Parameters
        ----------
        sitelinks : JsonValue
            The entity's sitelinks map.

        Returns
        -------
        tuple of str
            The sitelink URLs, in order.
        """
        return tuple(
            _as_str(_as_object(link).get("url"))
            for link in _as_object(sitelinks).values()
            if _as_str(_as_object(link).get("url"))
        )

    def search(
        self,
        text: str,
        *,
        lang: str | None = None,
        types: Sequence[str] | None = None,
    ) -> list[Candidate]:
        """Search Wikidata for candidate entities.

        Uses the ``wbsearchentities`` action API. Type constraints are not
        expressible in that API and are ignored; use :class:`ReconciliationKB`
        against the Wikidata reconciliation endpoint for type-filtered search.

        Parameters
        ----------
        text : str
            The surface text to link.
        lang : str or None, optional
            A language filter; defaults to the connector language.
        types : collections.abc.Sequence of str or None, optional
            Ignored by the action API.

        Returns
        -------
        list of lairs.integrations.kb.Candidate
            The ranked candidates.

        Raises
        ------
        httpx.HTTPStatusError
            If the action API returns a non-success status.
        """
        _ = types
        search_lang = lang if lang is not None else self.lang
        key = (text, search_lang)
        cached = self._search_cache.get(key)
        if cached is not None:
            return list(cached)
        params = {
            "action": "wbsearchentities",
            "search": text,
            "language": search_lang,
            "uselang": search_lang,
            "limit": DEFAULT_SEARCH_LIMIT,
            "format": "json",
        }
        response = self._client.get(self.api_endpoint, params=params)
        response.raise_for_status()
        body = _as_object(response.json())
        candidates: list[Candidate] = []
        for rank, hit in enumerate(_as_array(body.get("search"))):
            obj = _as_object(hit)
            candidates.append(
                Candidate(
                    ref=_as_str(obj.get("id")),
                    label=_as_str(obj.get("label")),
                    score=1.0 - rank / DEFAULT_SEARCH_LIMIT,
                ),
            )
        self._search_cache[key] = candidates
        return list(candidates)

    def neighbors(
        self,
        ref: str,
        *,
        rels: Sequence[str] | None = None,
    ) -> list[Edge]:
        """Expand a Wikidata entity's neighbourhood via SPARQL.

        Parameters
        ----------
        ref : str
            The Wikidata identifier or URI to expand.
        rels : collections.abc.Sequence of str or None, optional
            Property identifiers (for example ``P31``) to restrict the
            expansion to; all direct statements are returned when omitted.

        Returns
        -------
        list of lairs.integrations.kb.Edge
            The neighbouring edges.

        Raises
        ------
        httpx.HTTPStatusError
            If the SPARQL endpoint returns a non-success status.
        """
        qid = _qid(ref)
        query = self._neighbor_query(qid, rels)
        response = self._client.get(
            self.endpoint,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        response.raise_for_status()
        body = _as_object(response.json())
        bindings = _as_array(_as_object(body.get("results")).get("bindings"))
        edges: list[Edge] = []
        for binding in bindings:
            obj = _as_object(binding)
            relation = _as_str(_as_object(obj.get("p")).get("value"))
            target = _as_str(_as_object(obj.get("o")).get("value"))
            if relation and target:
                edges.append(
                    Edge(
                        source=qid,
                        relation=relation.removeprefix(_WD_PROP_PREFIX),
                        target=target.removeprefix(_WD_ENTITY_PREFIX),
                    ),
                )
        return edges

    def _neighbor_query(self, qid: str, rels: Sequence[str] | None) -> str:
        """Build the SPARQL query for a neighbourhood expansion.

        Parameters
        ----------
        qid : str
            The bare QID to expand.
        rels : collections.abc.Sequence of str or None
            Property identifiers to restrict to, if any.

        Returns
        -------
        str
            The SPARQL query string.
        """
        if rels:
            values = " ".join(f"wdt:{rel}" for rel in rels)
            predicate = f"VALUES ?p {{ {values} }}\n  ?s ?p ?o ."
        else:
            predicate = (
                '?s ?p ?o .\n  FILTER(STRSTARTS(STR(?p), "' + _WD_PROP_PREFIX + '"))'
            )
        return (
            "SELECT ?p ?o WHERE {\n"
            f"  BIND(wd:{qid} AS ?s)\n"
            f"  {predicate}\n"
            '  FILTER(STRSTARTS(STR(?o), "' + _WD_ENTITY_PREFIX + '"))\n'
            f"}} LIMIT {DEFAULT_NEIGHBOR_LIMIT}"
        )
