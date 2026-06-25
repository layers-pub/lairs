"""Unit tests for lairs.discovery.accelerator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lairs.discovery.accelerator import materialize_cards, search_accelerated
from lairs.discovery.cards import CardFreshness, CardProvenance, DatasetCard
from lairs.discovery.index import DiscoveryIndex
from lairs.discovery.models import DatasetSummary
from lairs.discovery.query import SearchQuery, search

if TYPE_CHECKING:
    from pathlib import Path

    from lairs.discovery.query import SearchHit

_NOW = datetime(2026, 6, 18, tzinfo=UTC)


def _card(  # noqa: PLR0913  (a test builder with many optional card facets)
    name: str,
    *,
    domain: str | None = None,
    language: str | None = None,
    license_id: str | None = None,
    expression_count: int | None = None,
    description: str | None = None,
    quality_metrics: tuple[str, ...] = (),
    annotation_rounds: int | None = None,
) -> DatasetCard:
    summary = DatasetSummary(
        uri=f"at://did:plc:x/pub.layers.corpus.corpus/{name}",
        did="did:plc:x",
        name=name,
        domain=domain,
        language=language,
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
        quality_metrics=quality_metrics,
        annotation_rounds=annotation_rounds,
    )


def _seeded_index(tmp_path: Path) -> DiscoveryIndex:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(
        _card(
            "climate corpus",
            domain="scientific",
            language="en",
            license_id="CC-BY-4.0",
            expression_count=100,
            description="weather and climate",
        ),
    )
    index.put_card(
        _card("legal corpus", domain="legal", language="en", expression_count=10)
    )
    index.put_card(
        _card("bio set", domain="biomedical", language="de", expression_count=500)
    )
    return index


def _uris(hits: list[SearchHit]) -> list[str]:
    return [hit.card.summary.uri for hit in hits]


def _assert_parity(index: DiscoveryIndex, query: SearchQuery, out_dir: Path) -> None:
    accelerated = search_accelerated(index, query, out_dir=out_dir)
    in_memory = search(index.cards(), query)
    assert _uris(accelerated) == _uris(in_memory)


def test_materialize_cards_writes_rebuildable_parquet(tmp_path: Path) -> None:
    index = _seeded_index(tmp_path)
    path = materialize_cards(index, tmp_path / "accel")
    assert path.exists()
    assert materialize_cards(index, tmp_path / "accel") == path


def test_accelerated_text_matches_in_memory(tmp_path: Path) -> None:
    _assert_parity(_seeded_index(tmp_path), SearchQuery(text="corpus"), tmp_path / "a")


def test_accelerated_domain_matches_in_memory(tmp_path: Path) -> None:
    _assert_parity(
        _seeded_index(tmp_path),
        SearchQuery(domain="biomedical"),
        tmp_path / "a",
    )


def test_accelerated_range_matches_in_memory(tmp_path: Path) -> None:
    _assert_parity(
        _seeded_index(tmp_path),
        SearchQuery(min_expressions=50),
        tmp_path / "a",
    )


def test_accelerated_empty_query_matches_in_memory(tmp_path: Path) -> None:
    _assert_parity(_seeded_index(tmp_path), SearchQuery(), tmp_path / "a")


def test_accelerated_no_match_returns_empty(tmp_path: Path) -> None:
    index = _seeded_index(tmp_path)
    hits = search_accelerated(index, SearchQuery(domain="news"), out_dir=tmp_path / "a")
    assert hits == []


def test_accelerated_license_matches_in_memory(tmp_path: Path) -> None:
    # "license" is a SQL reserved word; the pre-filter quotes the identifier.
    _assert_parity(
        _seeded_index(tmp_path),
        SearchQuery(license="CC-BY-4.0"),
        tmp_path / "a",
    )


def test_accelerated_max_expressions_matches_in_memory(tmp_path: Path) -> None:
    _assert_parity(
        _seeded_index(tmp_path),
        SearchQuery(max_expressions=100),
        tmp_path / "a",
    )


def test_accelerated_text_hits_description_matches_in_memory(tmp_path: Path) -> None:
    # "weather" appears only in a description, not a name, exercising the
    # combined name-OR-description text clause.
    _assert_parity(_seeded_index(tmp_path), SearchQuery(text="weather"), tmp_path / "a")


def test_accelerated_combined_facets_matches_in_memory(tmp_path: Path) -> None:
    _assert_parity(
        _seeded_index(tmp_path),
        SearchQuery(text="corpus", license="CC-BY-4.0", max_expressions=100),
        tmp_path / "a",
    )


def _metric_index(tmp_path: Path) -> DiscoveryIndex:
    index = DiscoveryIndex.init(tmp_path / "idx")
    index.put_card(
        _card(
            "kappa corpus",
            domain="scientific",
            expression_count=100,
            quality_metrics=("cohen-kappa",),
            annotation_rounds=3,
        ),
    )
    index.put_card(
        _card(
            "plain corpus",
            domain="scientific",
            expression_count=100,
        ),
    )
    return index


def test_accelerated_annotation_metric_matches_in_memory(tmp_path: Path) -> None:
    # annotation_metric is not a Parquet column, so the pre-filter keeps both
    # cards and the final in-memory search applies the exact metric predicate.
    index = _metric_index(tmp_path)
    query = SearchQuery(annotation_metric="cohen-kappa")
    _assert_parity(index, query, tmp_path / "a")
    hits = search_accelerated(index, query, out_dir=tmp_path / "b")
    assert _uris(hits) == ["at://did:plc:x/pub.layers.corpus.corpus/kappa corpus"]


def test_accelerated_min_rounds_matches_in_memory(tmp_path: Path) -> None:
    # min_annotation_rounds is also not materialized to Parquet; the relaxation
    # must still match the in-memory search exactly.
    index = _metric_index(tmp_path)
    query = SearchQuery(min_annotation_rounds=2)
    _assert_parity(index, query, tmp_path / "a")
    hits = search_accelerated(index, query, out_dir=tmp_path / "b")
    assert _uris(hits) == ["at://did:plc:x/pub.layers.corpus.corpus/kappa corpus"]
