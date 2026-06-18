"""In-memory search over the discovery index.

The primary, dependency-free query path: load ``DatasetCard`` records and filter
them with plain predicates, then rank. Discovery is at dataset scale (thousands
of corpora), so a linear scan is fast and an index server is unwarranted; the
optional DuckDB accelerator (see ``accelerator``) is only for larger scans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.discovery.cards import DatasetCard  # noqa: TC001  (runtime: didactic sort)

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["SearchHit", "SearchQuery", "search"]

_NAME_HIT_WEIGHT = 2.0
"""Score added when the query text matches the corpus name."""

_DESCRIPTION_HIT_WEIGHT = 1.0
"""Score added when the query text matches the corpus description."""

_SIGNAL_WEIGHT = 0.5
"""Score added per present metadata signal (size, quality, rounds)."""


class SearchQuery(dx.Model):
    """A structured, serializable query over dataset cards.

    Parameters
    ----------
    text : str or None
        A case-insensitive substring matched against name and description.
    domain : str or None
        A domain slug to match.
    language : str or None
        A language tag matched against the primary or listed languages.
    license : str or None
        A license identifier to match.
    min_expressions : int or None
        Keep cards with at least this many expressions.
    max_expressions : int or None
        Keep cards with at most this many expressions.
    annotation_metric : str or None
        Keep cards declaring this quality metric.
    min_annotation_rounds : int or None
        Keep cards declaring at least this many annotation rounds.
    """

    text: str | None = dx.field(default=None, description="name/description substring")
    domain: str | None = dx.field(default=None, description="domain slug to match")
    language: str | None = dx.field(default=None, description="language tag to match")
    license: str | None = dx.field(default=None, description="license to match")
    min_expressions: int | None = dx.field(
        default=None,
        description="minimum expression count",
    )
    max_expressions: int | None = dx.field(
        default=None,
        description="maximum expression count",
    )
    annotation_metric: str | None = dx.field(
        default=None,
        description="required quality metric slug",
    )
    min_annotation_rounds: int | None = dx.field(
        default=None,
        description="minimum annotation rounds",
    )


class SearchHit(dx.Model):
    """A matched dataset card with its ranking score.

    Parameters
    ----------
    card : DatasetCard
        The matched card.
    score : float
        The ranking score; higher ranks first.
    """

    card: dx.Embed[DatasetCard] = dx.field(description="the matched card")
    score: float = dx.field(description="ranking score, higher ranks first")


def _matches(card: DatasetCard, query: SearchQuery) -> bool:
    """Return whether a card satisfies every set facet of a query."""
    summary = card.summary
    count = summary.expression_count
    text = (query.text or "").lower()
    language_ok = (
        query.language is None
        or query.language == summary.language
        or query.language in summary.languages
    )
    text_ok = (
        query.text is None
        or text in summary.name.lower()
        or (summary.description is not None and text in summary.description.lower())
    )
    min_ok = query.min_expressions is None or (
        count is not None and count >= query.min_expressions
    )
    max_ok = query.max_expressions is None or (
        count is not None and count <= query.max_expressions
    )
    metric_ok = (
        query.annotation_metric is None
        or query.annotation_metric in card.quality_metrics
    )
    rounds_ok = query.min_annotation_rounds is None or (
        card.annotation_rounds is not None
        and card.annotation_rounds >= query.min_annotation_rounds
    )
    return all(
        (
            language_ok,
            query.domain is None or query.domain == summary.domain,
            query.license is None or query.license == summary.license,
            text_ok,
            min_ok,
            max_ok,
            metric_ok,
            rounds_ok,
        ),
    )


def _score(card: DatasetCard, query: SearchQuery) -> float:
    """Compute a deterministic relevance score for a matched card."""
    summary = card.summary
    score = 0.0
    if query.text is not None:
        text = query.text.lower()
        if text in summary.name.lower():
            score += _NAME_HIT_WEIGHT
        if summary.description is not None and text in summary.description.lower():
            score += _DESCRIPTION_HIT_WEIGHT
    if summary.expression_count is not None:
        score += _SIGNAL_WEIGHT
    if card.quality_metrics:
        score += _SIGNAL_WEIGHT
    if card.annotation_rounds is not None:
        score += _SIGNAL_WEIGHT
    return score


def search(cards: Iterable[DatasetCard], query: SearchQuery) -> list[SearchHit]:
    """Filter and rank dataset cards against a query.

    Parameters
    ----------
    cards : collections.abc.Iterable of DatasetCard
        The cards to search (for example ``DiscoveryIndex.cards()``).
    query : SearchQuery
        The query to apply.

    Returns
    -------
    list of SearchHit
        The matching cards, ranked by score then name.
    """
    hits = [
        SearchHit(card=card, score=_score(card, query))
        for card in cards
        if _matches(card, query)
    ]
    hits.sort(key=lambda hit: (-hit.score, hit.card.summary.name))
    return hits
