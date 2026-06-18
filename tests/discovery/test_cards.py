"""Unit tests for lairs.discovery.cards."""

from __future__ import annotations

from datetime import UTC, datetime

from lairs.discovery.cards import (
    CardFreshness,
    CardProvenance,
    DatasetCard,
    card_from_corpus,
    card_uri,
)
from lairs.records._generated.corpus import (
    AdjudicationSpec,
    AnnotationDesign,
    Corpus,
    QualityCriterion,
    RedundancySpec,
)

_NOW = datetime(2026, 6, 18, tzinfo=UTC)
_CORPUS_URI = "at://did:plc:x/pub.layers.corpus.corpus/a"


def _provenance() -> CardProvenance:
    return CardProvenance(
        source_did="did:plc:x",
        source_endpoint="https://pds.example",
        discovered_via="crawl",
        source_handle="alice.test",
    )


def _freshness() -> CardFreshness:
    return CardFreshness(first_seen_at=_NOW, last_updated_at=_NOW)


def test_card_uri_is_deterministic_and_namespaced() -> None:
    first = card_uri(_CORPUS_URI)
    assert first == card_uri(_CORPUS_URI)
    assert first.startswith("at://did:lairs:index/lairs.index.datasetCard/")
    assert card_uri("at://did:plc:y/pub.layers.corpus.corpus/b") != first


def test_card_from_corpus_projects_and_flattens() -> None:
    corpus = Corpus(
        name="demo",
        createdAt=_NOW,
        domain="biomedical",
        language="en",
        expressionCount=42,
        annotationDesign=AnnotationDesign(
            adjudication=AdjudicationSpec(method="majority-vote"),
            annotationRounds=2,
            redundancy=RedundancySpec(count=3),
            qualityCriteria=(QualityCriterion(metric="kappa"),),
        ),
    )
    card = card_from_corpus(
        _CORPUS_URI,
        corpus,
        provenance=_provenance(),
        freshness=_freshness(),
    )
    assert card.summary.name == "demo"
    assert card.summary.did == "did:plc:x"
    assert card.summary.handle == "alice.test"
    assert card.summary.expression_count == 42
    assert card.summary.has_adjudication is True
    assert card.annotation_rounds == 2
    assert card.adjudication_method == "majority-vote"
    assert card.redundancy_count == 3
    assert card.quality_metrics == ("kappa",)
    assert card.provenance.discovered_via == "crawl"


def test_card_from_corpus_without_design_is_empty_quality() -> None:
    corpus = Corpus(name="bare", createdAt=_NOW)
    card = card_from_corpus(
        _CORPUS_URI,
        corpus,
        provenance=_provenance(),
        freshness=_freshness(),
    )
    assert card.annotation_rounds is None
    assert card.adjudication_method is None
    assert card.redundancy_count is None
    assert card.quality_metrics == ()


def test_dataset_card_round_trips() -> None:
    corpus = Corpus(name="demo", createdAt=_NOW)
    card = card_from_corpus(
        _CORPUS_URI,
        corpus,
        provenance=_provenance(),
        freshness=_freshness(),
    )
    restored = DatasetCard.model_validate_json(card.model_dump_json())
    assert restored == card
