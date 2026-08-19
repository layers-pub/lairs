"""Unit tests for lairs.discovery.collection_summary."""

from __future__ import annotations

from datetime import UTC, datetime

from lairs.atproto.pds import RecordEnvelope
from lairs.discovery.collection_summary import (
    collection_from_value,
    listcollections_params,
    matches,
    summary_from_collection,
    summary_from_envelope,
)
from lairs.discovery.models import CollectionFilter, CollectionSummary
from lairs.records._generated.catalog import (
    Citation,
    Collection,
    ContentSummary,
)
from lairs.records._generated.defs import LicenseRef, Licensing

_CREATED = datetime(2026, 6, 18, tzinfo=UTC)
_URI = "at://did:plc:x/pub.layers.catalog.collection/a"
_PARENT = "at://did:plc:x/pub.layers.catalog.collection/parent"


def _collection(  # noqa: PLR0913  (a builder mirroring the record's many optional fields)
    *,
    description: str | None = None,
    kind_uri: str | None = None,
    languages: tuple[str, ...] = (),
    licensing: Licensing | None = None,
    access: str | None = None,
    stability: str | None = None,
    depth: int | None = None,
    parent_ref: str | None = None,
    root_ref: str | None = None,
    version: str | None = None,
    eprint_refs: tuple[str, ...] = (),
    citation: Citation | None = None,
    contents: tuple[ContentSummary, ...] = (),
) -> Collection:
    return Collection(
        name="UD English-EWT",
        kind="treebank",
        createdAt=_CREATED,
        description=description,
        kindUri=kind_uri,
        languages=languages,
        licensing=licensing,
        access=access,
        stability=stability,
        depth=depth,
        parentRef=parent_ref,
        rootRef=root_ref,
        version=version,
        eprintRefs=eprint_refs,
        citation=citation,
        contents=contents,
    )


def test_summary_from_collection_projects_fields() -> None:
    collection = _collection(
        description="an English treebank",
        kind_uri="at://did:plc:o/pub.layers.ontology.typeDef/treebank",
        languages=("en",),
        licensing=Licensing(licenses=(LicenseRef(spdx="CC-BY-SA-4.0"),)),
        access="open",
        stability="active",
        depth=2,
        parent_ref=_PARENT,
        root_ref=_PARENT,
        version="2.18",
        eprint_refs=("at://did:plc:e/pub.layers.eprint.eprint/x",),
        citation=Citation(creditPolicy="cite-self"),
        contents=(
            ContentSummary(
                produceCollection="pub.layers.annotation.annotationLayer",
                countSource="computed",
                modality="text",
                subkind="dependency",
                sourceMethod="manual",
            ),
        ),
    )
    summary = summary_from_collection(
        collection,
        uri=_URI,
        did="did:plc:x",
        handle="ud.test",
        source_endpoint="https://pds.example",
        member_count=0,
        produce_count=3,
    )
    assert summary.name == "UD English-EWT"
    assert summary.kind == "treebank"
    assert summary.kind_uri is not None
    assert summary.languages == ("en",)
    assert summary.license == "CC-BY-SA-4.0"
    assert summary.access == "open"
    assert summary.stability == "active"
    assert summary.depth == 2
    assert summary.parent_ref == _PARENT
    assert summary.root_ref == _PARENT
    assert summary.version == "2.18"
    assert summary.citable is True
    assert summary.member_count == 0
    assert summary.produce_count == 3
    assert summary.modalities == ("text",)
    assert summary.annotation_subkinds == ("dependency",)
    assert summary.source_methods == ("manual",)
    assert summary.created_at == _CREATED.isoformat()
    assert summary.eprint_refs == ("at://did:plc:e/pub.layers.eprint.eprint/x",)
    assert summary.source_endpoint == "https://pds.example"


def test_citable_only_for_cite_self_or_both() -> None:
    for policy, expected in (
        ("cite-self", True),
        ("cite-both", True),
        ("cite-children", False),
        ("cite-parent", False),
    ):
        summary = summary_from_collection(
            _collection(citation=Citation(creditPolicy=policy)),
            uri=_URI,
            did="did:plc:x",
        )
        assert summary.citable is expected
    # no citation block at all is not citable.
    bare = summary_from_collection(_collection(), uri=_URI, did="did:plc:x")
    assert bare.citable is False


def test_content_facets_are_distinct_and_sorted() -> None:
    collection = _collection(
        contents=(
            ContentSummary(
                produceCollection="pub.layers.annotation.annotationLayer",
                countSource="computed",
                modality="eeg",
                subkind="dependency",
            ),
            ContentSummary(
                produceCollection="pub.layers.media.media",
                countSource="declared",
                modality="audio",
                subkind="coreference",
            ),
        ),
    )
    summary = summary_from_collection(collection, uri=_URI, did="did:plc:x")
    assert summary.modalities == ("audio", "eeg")
    assert summary.annotation_subkinds == ("coreference", "dependency")


def test_collection_from_value_decodes_and_drops_type() -> None:
    collection = collection_from_value(
        {
            "$type": "pub.layers.catalog.collection",
            "name": "demo",
            "kind": "corpus",
            "createdAt": "2026-06-18T00:00:00Z",
        },
    )
    assert collection is not None
    assert collection.name == "demo"
    assert collection.kind == "corpus"


def test_collection_from_value_invalid_returns_none() -> None:
    assert collection_from_value({"createdAt": "2026-06-18T00:00:00Z"}) is None
    assert collection_from_value("nope") is None


def test_summary_from_envelope_decodes_collection() -> None:
    summary = summary_from_envelope(
        RecordEnvelope(
            uri=_URI,
            cid="bafy",
            value={
                "$type": "pub.layers.catalog.collection",
                "name": "demo",
                "kind": "treebank",
                "createdAt": "2026-06-18T00:00:00Z",
                "languages": ["en"],
            },
        ),
    )
    assert summary is not None
    assert summary.name == "demo"
    assert summary.did == "did:plc:x"  # derived from the envelope authority
    assert summary.languages == ("en",)


def test_summary_from_envelope_rejects_foreign_collection() -> None:
    envelope = RecordEnvelope(
        uri="at://did:plc:x/pub.layers.corpus.corpus/a",
        cid="bafy",
        value={"name": "not a collection", "createdAt": "2026-06-18T00:00:00Z"},
    )
    assert summary_from_envelope(envelope) is None


def _summary(*, citable: bool = True) -> CollectionSummary:
    return CollectionSummary(
        uri=_URI,
        did="did:plc:x",
        name="UD English-EWT",
        kind="treebank",
        description="english dependency treebank",
        languages=("en",),
        license="CC-BY-SA-4.0",
        access="open",
        stability="active",
        depth=1,
        parent_ref=_PARENT,
        root_ref=_PARENT,
        citable=citable,
        modalities=("text",),
        annotation_subkinds=("dependency",),
        source_methods=("manual",),
    )


def test_matches_none_filter_passes() -> None:
    assert matches(_summary(), None) is True


def test_matches_facets() -> None:
    assert matches(_summary(), CollectionFilter(kind=("treebank",))) is True
    assert matches(_summary(), CollectionFilter(kind=("lexicon",))) is False
    assert matches(_summary(), CollectionFilter(languages=("en",))) is True
    assert matches(_summary(), CollectionFilter(languages=("fr",))) is False
    assert matches(_summary(), CollectionFilter(spdx=("CC-BY-SA-4.0",))) is True
    assert matches(_summary(), CollectionFilter(spdx=("MIT",))) is False
    assert matches(_summary(), CollectionFilter(access=("open",))) is True
    assert matches(_summary(), CollectionFilter(stability=("frozen",))) is False
    assert matches(_summary(), CollectionFilter(parent_ref=_PARENT)) is True
    assert matches(_summary(), CollectionFilter(depth=1)) is True
    assert matches(_summary(), CollectionFilter(depth=0)) is False
    assert matches(_summary(), CollectionFilter(citable_only=True)) is True
    not_citable = _summary(citable=False)
    assert matches(not_citable, CollectionFilter(citable_only=True)) is False
    assert matches(_summary(), CollectionFilter(modality=("text",))) is True
    dependency = CollectionFilter(annotation_subkind=("dependency",))
    assert matches(_summary(), dependency) is True
    assert matches(_summary(), CollectionFilter(annotation_subkind=("frame",))) is False
    assert matches(_summary(), CollectionFilter(text="DEPENDENCY")) is True
    assert matches(_summary(), CollectionFilter(text="lexicon")) is False


def test_listcollections_params_pushes_scalar_facets() -> None:
    assert listcollections_params("did:plc:x", None) == {"repo": "did:plc:x"}
    pushed = listcollections_params(
        "did:plc:x",
        CollectionFilter(
            text="ewt",
            parent_ref=_PARENT,
            root_ref=_PARENT,
            depth=1,
            citable_only=True,
            sort="name",
            # array facets are applied client-side, not pushed
            kind=("treebank",),
            languages=("en",),
        ),
    )
    assert pushed == {
        "repo": "did:plc:x",
        "q": "ewt",
        "parentRef": _PARENT,
        "rootRef": _PARENT,
        "depth": 1,
        "citableOnly": True,
        "sort": "name",
    }
