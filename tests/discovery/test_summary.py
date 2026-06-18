"""Unit tests for lairs.discovery.summary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from lairs.atproto.pds import RecordEnvelope
from lairs.discovery.models import DatasetFilter, DatasetSummary
from lairs.discovery.summary import (
    listcorpora_params,
    matches,
    summary_from_corpus,
    summary_from_envelope,
)
from lairs.records._generated.corpus import (
    AdjudicationSpec,
    AnnotationDesign,
    Corpus,
)

if TYPE_CHECKING:
    from lairs._types import JsonValue

_CREATED = datetime(2026, 6, 18, tzinfo=UTC)
_URI = "at://did:plc:x/pub.layers.corpus.corpus/a"


def test_summary_from_corpus_projects_fields() -> None:
    corpus = Corpus(
        name="demo",
        createdAt=_CREATED,
        description="a demo corpus",
        domain="biomedical",
        language="en",
        languages=("en", "de"),
        license="CC-BY-4.0",
        version="1.0",
        expressionCount=42,
        ontologyRefs=("at://did:plc:o/pub.layers.ontology.ontology/x",),
    )
    summary = summary_from_corpus(
        corpus,
        uri=_URI,
        did="did:plc:x",
        handle="alice.test",
        source_endpoint="https://pds.example",
    )
    assert summary.name == "demo"
    assert summary.did == "did:plc:x"
    assert summary.handle == "alice.test"
    assert summary.domain == "biomedical"
    assert summary.languages == ("en", "de")
    assert summary.license == "CC-BY-4.0"
    assert summary.expression_count == 42
    assert summary.created_at == _CREATED.isoformat()
    assert summary.ontology_refs == ("at://did:plc:o/pub.layers.ontology.ontology/x",)
    assert summary.has_adjudication is False
    assert summary.source_endpoint == "https://pds.example"


def test_summary_from_corpus_detects_adjudication() -> None:
    corpus = Corpus(
        name="demo",
        createdAt=_CREATED,
        annotationDesign=AnnotationDesign(
            adjudication=AdjudicationSpec(method="majority-vote"),
        ),
    )
    summary = summary_from_corpus(corpus, uri=_URI, did="did:plc:x")
    assert summary.has_adjudication is True


def _envelope(value: JsonValue) -> RecordEnvelope:
    return RecordEnvelope(uri=_URI, cid="bafy", value=value)


def test_summary_from_envelope_decodes_corpus() -> None:
    summary = summary_from_envelope(
        _envelope(
            {
                "$type": "pub.layers.corpus.corpus",
                "name": "demo",
                "createdAt": "2026-06-18T00:00:00Z",
                "language": "en",
            },
        ),
        source_endpoint="https://pds.example",
    )
    assert summary is not None
    assert summary.name == "demo"
    assert summary.did == "did:plc:x"  # derived from the envelope authority
    assert summary.language == "en"


def test_summary_from_envelope_rejects_foreign_collection() -> None:
    envelope = RecordEnvelope(
        uri="at://did:plc:x/app.bsky.feed.post/a",
        cid="bafy",
        value={"text": "hi"},
    )
    assert summary_from_envelope(envelope) is None


def test_summary_from_envelope_rejects_invalid_corpus() -> None:
    # missing the required name field => decode fails => None, not a crash.
    assert (
        summary_from_envelope(_envelope({"createdAt": "2026-06-18T00:00:00Z"})) is None
    )


def _summary(
    *,
    language: str | None = "en",
    languages: tuple[str, ...] = ("en",),
    expression_count: int | None = 100,
    has_adjudication: bool = True,
) -> DatasetSummary:
    return DatasetSummary(
        uri=_URI,
        did="did:plc:x",
        name="climate corpus",
        description="weather and climate text",
        domain="scientific",
        language=language,
        languages=languages,
        license="CC-BY-4.0",
        expression_count=expression_count,
        has_adjudication=has_adjudication,
    )


def test_matches_none_filter_passes() -> None:
    assert matches(_summary(), None) is True


def test_matches_facets() -> None:
    assert matches(_summary(), DatasetFilter(domain="scientific")) is True
    assert matches(_summary(), DatasetFilter(domain="legal")) is False
    assert matches(_summary(), DatasetFilter(license="CC-BY-4.0")) is True
    assert matches(_summary(), DatasetFilter(language="en")) is True
    assert matches(_summary(), DatasetFilter(language="fr")) is False
    assert matches(_summary(), DatasetFilter(has_adjudication=True)) is True
    assert matches(_summary(), DatasetFilter(has_adjudication=False)) is False


def test_matches_language_membership() -> None:
    summary = _summary(language="en", languages=("en", "de"))
    assert matches(summary, DatasetFilter(language="de")) is True


def test_matches_expression_ranges() -> None:
    assert matches(_summary(), DatasetFilter(min_expression_count=50)) is True
    assert matches(_summary(), DatasetFilter(min_expression_count=200)) is False
    assert matches(_summary(), DatasetFilter(max_expression_count=200)) is True
    assert matches(_summary(), DatasetFilter(max_expression_count=50)) is False
    none_count = _summary(expression_count=None)
    assert matches(none_count, DatasetFilter(min_expression_count=1)) is False


def test_matches_text_substring() -> None:
    assert matches(_summary(), DatasetFilter(text="CLIMATE")) is True
    assert matches(_summary(), DatasetFilter(text="weather")) is True
    assert matches(_summary(), DatasetFilter(text="legal")) is False


def test_listcorpora_params_pushes_server_side_facets() -> None:
    assert listcorpora_params("did:plc:x", None) == {"repo": "did:plc:x"}
    pushed = listcorpora_params(
        "did:plc:x",
        DatasetFilter(language="en", domain="biomedical", license="CC-BY-4.0"),
    )
    assert pushed == {"repo": "did:plc:x", "language": "en", "domain": "biomedical"}
