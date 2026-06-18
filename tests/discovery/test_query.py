"""Unit tests for lairs.discovery.query."""

from __future__ import annotations

from datetime import UTC, datetime

from lairs.discovery.cards import CardFreshness, CardProvenance, DatasetCard
from lairs.discovery.models import DatasetSummary
from lairs.discovery.query import SearchQuery, search

_NOW = datetime(2026, 6, 18, tzinfo=UTC)


def _card(  # noqa: PLR0913  (a test builder with many optional card facets)
    name: str,
    *,
    domain: str | None = None,
    language: str | None = None,
    languages: tuple[str, ...] = (),
    license_id: str | None = None,
    expression_count: int | None = None,
    description: str | None = None,
    metrics: tuple[str, ...] = (),
    rounds: int | None = None,
) -> DatasetCard:
    summary = DatasetSummary(
        uri=f"at://did:plc:x/pub.layers.corpus.corpus/{name}",
        did="did:plc:x",
        name=name,
        domain=domain,
        language=language,
        languages=languages,
        license=license_id,
        expression_count=expression_count,
        description=description,
    )
    return DatasetCard(
        summary=summary,
        provenance=CardProvenance(
            source_did="did:plc:x",
            source_endpoint="https://pds.example",
            discovered_via="seed",
        ),
        freshness=CardFreshness(first_seen_at=_NOW, last_updated_at=_NOW),
        quality_metrics=metrics,
        annotation_rounds=rounds,
    )


def test_search_empty_query_returns_all() -> None:
    cards = [_card("a"), _card("b")]
    assert len(search(cards, SearchQuery())) == 2


def test_search_text_matches_name_and_description() -> None:
    cards = [
        _card("climate corpus", description="weather"),
        _card("legal corpus", description="court rulings"),
    ]
    hits = search(cards, SearchQuery(text="CLIMATE"))
    assert [hit.card.summary.name for hit in hits] == ["climate corpus"]
    body = search(cards, SearchQuery(text="court"))
    assert [hit.card.summary.name for hit in body] == ["legal corpus"]


def test_search_facets() -> None:
    cards = [
        _card("a", domain="biomedical", language="en", license_id="CC-BY-4.0"),
        _card("b", domain="legal", language="fr"),
    ]
    assert len(search(cards, SearchQuery(domain="biomedical"))) == 1
    assert len(search(cards, SearchQuery(language="fr"))) == 1
    assert len(search(cards, SearchQuery(license="CC-BY-4.0"))) == 1


def test_search_language_membership() -> None:
    cards = [_card("a", language="en", languages=("en", "de"))]
    assert len(search(cards, SearchQuery(language="de"))) == 1


def test_search_expression_ranges() -> None:
    cards = [_card("a", expression_count=100)]
    assert len(search(cards, SearchQuery(min_expressions=50))) == 1
    assert len(search(cards, SearchQuery(min_expressions=200))) == 0
    assert len(search(cards, SearchQuery(max_expressions=50))) == 0


def test_search_quality_predicates() -> None:
    cards = [_card("a", metrics=("kappa", "alpha"), rounds=3)]
    assert len(search(cards, SearchQuery(annotation_metric="kappa"))) == 1
    assert len(search(cards, SearchQuery(annotation_metric="f1"))) == 0
    assert len(search(cards, SearchQuery(min_annotation_rounds=2))) == 1
    assert len(search(cards, SearchQuery(min_annotation_rounds=5))) == 0


def test_search_ranks_name_hit_above_description_hit() -> None:
    cards = [
        _card("weather notes", description="about climate"),
        _card("climate corpus", description="general text"),
    ]
    hits = search(cards, SearchQuery(text="climate"))
    # the name match scores higher than the description match.
    assert hits[0].card.summary.name == "climate corpus"
    assert hits[0].score > hits[1].score
