"""Unit tests for lairs.discovery.cards."""

from __future__ import annotations

from datetime import UTC, datetime

from lairs.discovery.cards import (
    CardFreshness,
    CardProvenance,
    CollectionCard,
    DatasetCard,
    card_from_collection,
    card_from_corpus,
    card_uri,
    collection_card_uri,
)
from lairs.records._generated.catalog import Collection
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
        languages=("en",),
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


_COLLECTION_URI = "at://did:plc:x/pub.layers.catalog.collection/c"


def test_collection_card_uri_is_deterministic_and_namespaced() -> None:
    first = collection_card_uri(_COLLECTION_URI)
    assert first == collection_card_uri(_COLLECTION_URI)
    assert first.startswith("at://did:lairs:index/lairs.index.collectionCard/")
    # a collection card and a dataset card of the same URI live under different NSIDs.
    assert first != card_uri(_COLLECTION_URI)


def test_card_from_collection_projects_and_flags_container() -> None:
    collection = Collection(
        name="Universal Dependencies",
        kind="project",
        createdAt=_NOW,
    )
    card = card_from_collection(
        _COLLECTION_URI,
        collection,
        provenance=_provenance(),
        freshness=_freshness(),
    )
    assert card.summary.name == "Universal Dependencies"
    assert card.summary.kind == "project"
    assert card.summary.did == "did:plc:x"
    assert card.summary.handle == "alice.test"
    # a project habitually contains other collections.
    assert card.is_container is True


def test_card_from_collection_leaf_is_not_container() -> None:
    collection = Collection(name="UD English-EWT", kind="treebank", createdAt=_NOW)
    card = card_from_collection(
        _COLLECTION_URI,
        collection,
        provenance=_provenance(),
        freshness=_freshness(),
    )
    assert card.is_container is False


def test_collection_card_round_trips() -> None:
    collection = Collection(name="demo", kind="corpus", createdAt=_NOW)
    card = card_from_collection(
        _COLLECTION_URI,
        collection,
        provenance=_provenance(),
        freshness=_freshness(),
    )
    restored = CollectionCard.model_validate_json(card.model_dump_json())
    assert restored == card
