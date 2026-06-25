"""Lexical-semantic knowledge-base connector backed by glazing.

Grounds lemmas, senses, frames, and rolesets against FrameNet, PropBank,
VerbNet, and WordNet through the glazing library's unified, type-safe
interface, with SemLink-style cross-reference resolution. Requires the
``lairs[lexical]`` extra (``glazing>=0.2``) at runtime; glazing is imported
lazily inside the connector, never at module import, so importing this module
never pulls in the optional dependency.

The connector maps glazing's typed search results onto :class:`Candidate`,
resolved entries onto :class:`Entity`, and cross-reference links onto
:class:`Edge`, mapping link confidences onto edge weights via the relation
label. glazing's objects are consumed through narrow :class:`~typing.Protocol`
shims so this module stays strictly typed without importing the library or
using ``Any``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from lairs.integrations.kb import Candidate, Edge, Entity

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType, TracebackType

__all__ = ["GlazingKB", "GlazingNotInstalledError"]

_LEXICAL_EXTRA_HINT = (
    "the glazing connector requires the optional lexical dependencies; "
    "install them with `pip install 'lairs[lexical]'` and run `glazing init` "
    "to download the FrameNet/PropBank/VerbNet/WordNet data"
)
"""The actionable hint shown when glazing is missing."""

_CONFIDENCE_KEY = "confidence_scores"
"""The key under which the cross-reference index returns per-link confidences."""

type XrefLinks = dict[str, str | list[str] | dict[str, dict[str, float]]]
"""The shape of a glazing cross-reference resolution.

Most keys map a target-resource name to a list of resolved identifiers (or a
single identifier string for a one-to-one relation); the ``confidence_scores``
key maps each relation to a per-target score mapping.
"""


class GlazingNotInstalledError(ImportError):
    """The optional glazing library is not installed.

    Raised, with an actionable install hint, when a glazing-backed method is
    called but the ``lairs[lexical]`` extra is absent. Subclasses
    :class:`ImportError` so callers can catch it as an import problem.
    """


@runtime_checkable
class _SearchHit(Protocol):
    """The shape of a glazing unified-search result consumed here.

    glazing search hits expose at least a dataset name, an entry name, and a
    score; this protocol pins exactly the attributes the connector reads.
    """

    @property
    def dataset(self) -> str:
        """The source dataset name (framenet, propbank, verbnet, wordnet)."""
        ...

    @property
    def name(self) -> str:
        """The entry name or identifier."""
        ...

    @property
    def score(self) -> float:
        """The relevance score."""
        ...


@runtime_checkable
class _UnifiedSearch(Protocol):
    """The shape of ``glazing.search.UnifiedSearch`` consumed here."""

    def search(self, query: str) -> Sequence[_SearchHit]:
        """Search every loaded resource for a query string.

        Parameters
        ----------
        query : str
            The lemma or surface form to search.

        Returns
        -------
        collections.abc.Sequence
            The ranked search hits.
        """
        ...


@runtime_checkable
class _CrossReferenceIndex(Protocol):
    """The shape of ``glazing.references.index.CrossReferenceIndex``."""

    def resolve(self, ref: str, *, source: str) -> XrefLinks:
        """Resolve an entry's cross-references to other resources.

        Parameters
        ----------
        ref : str
            The entry identifier (for example a PropBank roleset ``give.01``).
        source : str
            The source resource name.

        Returns
        -------
        XrefLinks
            A mapping from target-resource keys (for example
            ``verbnet_classes``) to lists of identifiers, plus a
            ``confidence_scores`` entry.
        """
        ...


def _link_targets(links: XrefLinks, relation: str) -> list[str]:
    """Return the resolved identifiers for one cross-reference relation.

    A relation value may be a list of identifiers or, for a one-to-one
    relation, a single identifier string; both are normalised to a list. The
    ``confidence_scores`` key holds a nested mapping rather than targets and is
    never treated as a relation here, so its ``dict`` value yields no targets.

    Parameters
    ----------
    links : XrefLinks
        The cross-reference resolution mapping.
    relation : str
        The target-resource key.

    Returns
    -------
    list of str
        The resolved target identifiers, or an empty list if absent.
    """
    targets = links.get(relation)
    if isinstance(targets, str):
        return [targets]
    if isinstance(targets, list):
        return [target for target in targets if isinstance(target, str)]
    return []


def _confidence_for(
    links: XrefLinks,
    relation: str,
    target: str,
) -> float:
    """Look up the confidence for one resolved cross-reference link.

    Parameters
    ----------
    links : dict
        The cross-reference resolution mapping.
    relation : str
        The target-resource key (for example ``verbnet_classes``).
    target : str
        The resolved target identifier.

    Returns
    -------
    float
        The link confidence, or ``1.0`` when none is reported.
    """
    scores = links.get(_CONFIDENCE_KEY)
    if not isinstance(scores, dict):
        return 1.0
    by_target = scores.get(relation)
    if isinstance(by_target, dict):
        value = by_target.get(target)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 1.0


class GlazingKB:
    """A lexical-semantic connector over glazing's four resources.

    Parameters
    ----------
    data_dir : str or None, optional
        The local glazing data directory; defaults to the glazing default
        established by ``glazing init``.
    default_source : str, optional
        The resource a bare identifier (one without a ``resource:`` prefix) is
        attributed to in :meth:`resolve`, :meth:`neighbors`, and the
        resource-prefix split of :meth:`search`. Defaults to ``propbank``; set
        it to ``verbnet``, ``framenet``, or ``wordnet`` when working with bare
        identifiers from another resource.

    Raises
    ------
    GlazingNotInstalledError
        Lazily, when a glazing-backed method is first called and the
        ``lairs[lexical]`` extra is not installed. Construction never imports
        glazing.
    """

    name = "glazing"

    def __init__(
        self,
        data_dir: str | None = None,
        *,
        default_source: str = "propbank",
    ) -> None:
        self.data_dir = data_dir
        self.default_source = default_source
        self._search: _UnifiedSearch | None = None
        self._xref: _CrossReferenceIndex | None = None
        self._entity_cache: dict[str, Entity] = {}
        self._search_cache: dict[str, list[Candidate]] = {}
        self._neighbor_cache: dict[str, list[Edge]] = {}

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
        """Exit the context manager.

        glazing holds no resources that need closing, so this is a no-op kept
        for symmetry with the other connectors.

        Parameters
        ----------
        _exc_type : type[BaseException] or None
            The exception type, if the block raised.
        _exc : BaseException or None
            The exception instance, if the block raised.
        _tb : types.TracebackType or None
            The traceback, if the block raised.
        """

    def _searcher(self) -> _UnifiedSearch:
        """Return the unified searcher, importing glazing on first use.

        Returns
        -------
        _UnifiedSearch
            The lazily constructed glazing unified searcher.

        Raises
        ------
        GlazingNotInstalledError
            If the glazing library is not installed.
        """
        if self._search is None:
            module = _import_glazing("glazing.search")
            factory: type[_UnifiedSearch] = module.UnifiedSearch
            self._search = factory()
        return self._search

    def _index(self) -> _CrossReferenceIndex:
        """Return the cross-reference index, importing glazing on first use.

        Returns
        -------
        _CrossReferenceIndex
            The lazily constructed glazing cross-reference index.

        Raises
        ------
        GlazingNotInstalledError
            If the glazing library is not installed.
        """
        if self._xref is None:
            module = _import_glazing("glazing.references.index")
            factory: type[_CrossReferenceIndex] = module.CrossReferenceIndex
            self._xref = factory()
        return self._xref

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
            Ignored; glazing's resources are English-only.
        types : collections.abc.Sequence of str or None, optional
            Resource names (``framenet``, ``propbank``, ``verbnet``,
            ``wordnet``) to restrict the results to; all resources when
            omitted.

        Returns
        -------
        list of lairs.integrations.kb.Candidate
            The ranked candidates, identifiers prefixed by their resource.

        Raises
        ------
        GlazingNotInstalledError
            If the glazing library is not installed.
        """
        _ = lang
        cached = self._search_cache.get(text)
        if cached is None:
            hits = self._searcher().search(text)
            cached = [
                Candidate(
                    ref=f"{hit.dataset}:{hit.name}",
                    label=hit.name,
                    score=float(hit.score),
                )
                for hit in hits
            ]
            self._search_cache[text] = cached
        if types is None:
            return list(cached)
        allowed = set(types)
        return [
            candidate
            for candidate in cached
            if candidate.ref.split(":", 1)[0] in allowed
        ]

    def resolve(self, ref: str) -> Entity:
        """Resolve a lexical identifier to an entity.

        The entity's ``same_as`` carries the resolved cross-references so a
        single resolve doubles as a SemLink lookup.

        Parameters
        ----------
        ref : str
            The lexical identifier, optionally ``resource:id`` (for example
            ``propbank:give.01``); a bare id is attributed to the connector's
            ``default_source``.

        Returns
        -------
        lairs.integrations.kb.Entity
            The resolved lexical entity.

        Raises
        ------
        GlazingNotInstalledError
            If the glazing library is not installed.
        """
        cached = self._entity_cache.get(ref)
        if cached is not None:
            return cached
        source, ident = self._split(ref)
        links = self._index().resolve(ident, source=source)
        same_as = tuple(
            f"{relation}:{target}"
            for relation in links
            if relation != _CONFIDENCE_KEY
            for target in _link_targets(links, relation)
        )
        entity = Entity(
            ref=ref,
            label=ident,
            types=(source,),
            same_as=same_as,
        )
        self._entity_cache[ref] = entity
        return entity

    def neighbors(
        self,
        ref: str,
        *,
        rels: Sequence[str] | None = None,
    ) -> list[Edge]:
        """Expand a lexical entry's cross-references.

        Each resolved link becomes an edge whose relation is the target
        resource and whose weight is folded into the relation when glazing
        reports a confidence below one (for example ``verbnet_classes@0.85``).

        Parameters
        ----------
        ref : str
            The lexical identifier, optionally ``resource:id``.
        rels : collections.abc.Sequence of str or None, optional
            Target-resource keys (for example ``verbnet_classes``) to restrict
            the expansion to.

        Returns
        -------
        list of lairs.integrations.kb.Edge
            The cross-reference edges (for example VerbNet class links).

        Raises
        ------
        GlazingNotInstalledError
            If the glazing library is not installed.
        """
        cached = self._neighbor_cache.get(ref)
        if cached is None:
            source, ident = self._split(ref)
            links = self._index().resolve(ident, source=source)
            cached = []
            for relation in links:
                if relation == _CONFIDENCE_KEY:
                    continue
                for target in _link_targets(links, relation):
                    confidence = _confidence_for(links, relation, target)
                    label = (
                        relation if confidence >= 1.0 else f"{relation}@{confidence:g}"
                    )
                    cached.append(Edge(source=ref, relation=label, target=target))
            self._neighbor_cache[ref] = cached
        if rels is None:
            return list(cached)
        allowed = set(rels)
        return [edge for edge in cached if edge.relation.split("@", 1)[0] in allowed]

    def _split(self, ref: str) -> tuple[str, str]:
        """Split a ``resource:id`` reference, defaulting to ``default_source``.

        Parameters
        ----------
        ref : str
            The lexical identifier.

        Returns
        -------
        tuple of str
            The ``(source, identifier)`` pair.
        """
        if ":" in ref:
            source, ident = ref.split(":", 1)
            return source, ident
        return self.default_source, ref


def _import_glazing(name: str) -> ModuleType:
    """Import a glazing submodule, translating absence into a clear error.

    Parameters
    ----------
    name : str
        The fully qualified glazing submodule name.

    Returns
    -------
    types.ModuleType
        The imported module.

    Raises
    ------
    GlazingNotInstalledError
        If the glazing library is not installed.
    """
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise GlazingNotInstalledError(_LEXICAL_EXTRA_HINT) from exc
