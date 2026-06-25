"""Shared fixtures for the TUI tests.

A canonical materialized corpus (``corpus_dir``) and a seeded discovery index
(``index_path``) so the engine and the app are exercised against deterministic
data with known query results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lairs.discovery.cards import CardFreshness, CardProvenance, DatasetCard
from lairs.discovery.index import DiscoveryIndex
from lairs.discovery.models import DatasetSummary
from lairs.records._generated import (
    annotation,
    corpus,
    defs,
    eprint,
    expression,
    graph,
    judgment,
    media,
    ontology,
    persona,
    resource,
    segmentation,
)
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 6, 18, tzinfo=UTC)
_DID = "did:plc:browsefixture"


def _uri(collection: str, rkey: str) -> str:
    """Build an AT-URI in the fixture's repository."""
    return f"at://{_DID}/{collection}/{rkey}"


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    """Write a canonical two-view corpus and return its directory.

    Three expressions and three annotation layers. ``L1`` is a five-token POS
    sequence ``DET ADJ ADJ NOUN VERB``; ``L2`` is ``DET NOUN``; ``L3`` is
    ``DET _ NOUN`` with a gap at ``token_index`` 1. These shapes pin the
    concordance and CQL results the tests assert.
    """
    pq.write_table(
        pa.table(
            {
                "id": ["s1", "s2", "s3"],
                "kind": ["sentence", "sentence", "utterance"],
                "text": [
                    "The quick brown fox jumps over the lazy dog.",
                    "A brown dog runs fast.",
                    "Run, dog, run!",
                ],
            },
        ),
        tmp_path / "expressions.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "layer_uri": ["L1", "L1", "L1", "L1", "L1", "L2", "L2", "L3", "L3"],
                "annotation_index": [0, 1, 2, 3, 4, 0, 1, 0, 1],
                "label": [
                    "DET",
                    "ADJ",
                    "ADJ",
                    "NOUN",
                    "VERB",
                    "DET",
                    "NOUN",
                    "DET",
                    "NOUN",
                ],
                "subkind": ["pos"] * 9,
                "value": [
                    "the",
                    "quick",
                    "brown",
                    "fox",
                    "jumps",
                    "a",
                    "dog",
                    "the",
                    "dog",
                ],
                "token_index": [0, 1, 2, 3, 4, 0, 1, 0, 2],
            },
        ),
        tmp_path / "annotations.parquet",
    )
    return tmp_path


def make_card(  # noqa: PLR0913 - a card builder with many optional facets
    name: str,
    *,
    domain: str | None = None,
    language: str | None = None,
    license_id: str | None = None,
    expression_count: int | None = None,
    description: str | None = None,
) -> DatasetCard:
    """Build a dataset card for the seeded index, mirroring the discovery tests."""
    summary = DatasetSummary(
        uri=f"at://did:plc:x/pub.layers.corpus.corpus/{name.replace(' ', '_')}",
        did="did:plc:x",
        name=name,
        domain=domain,
        language=language,
        languages=(language,) if language else (),
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
    )


@pytest.fixture
def index_path(tmp_path: Path) -> str:
    """Build a discovery index of three cards and return its directory path."""
    path = tmp_path / "idx"
    index = DiscoveryIndex.init(path)
    index.put_card(
        make_card(
            "climate corpus",
            domain="scientific",
            language="en",
            license_id="CC-BY-4.0",
            expression_count=100,
            description="weather and climate text",
        ),
    )
    index.put_card(
        make_card("legal corpus", domain="legal", language="en", expression_count=10),
    )
    index.put_card(
        make_card("bio set", domain="biomedical", language="de", expression_count=500),
    )
    return str(path)


@pytest.fixture
def markup_repo(tmp_path: Path) -> Path:
    """Seed a repository whose fields contain Rich-markup and bracket characters.

    Used to prove the record list and detail panel treat record content as
    literal text, never as console markup that could be interpreted or break
    rendering.
    """
    repo = Repository.init(tmp_path / "mrepo")
    cor = _uri("pub.layers.corpus.corpus", "c")
    repo.save(
        cor,
        corpus.Corpus(
            name="[bold]Tricky[/bold]",
            createdAt=_NOW,
            domain="a[b]c",
            expressionCount=1,
        ),
    )
    expr = _uri("pub.layers.expression.expression", "e")
    repo.save(
        expr,
        expression.Expression(
            id="e",
            kind="sentence",
            createdAt=_NOW,
            text="see [1] and [link](x) and `code` and [/red] markup",
        ),
    )
    repo.save(
        _uri("pub.layers.corpus.membership", "m"),
        corpus.Membership(corpusRef=cor, expressionRef=expr, createdAt=_NOW),
    )
    return repo.path


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """Seed a repository with one record of every type the Browse tab renders.

    Covers each bespoke renderer with its related records: an ontology with two
    type definitions (one relation with a gloss, one entity), an experiment with
    a judgment set and an agreement report, an edge set with two relation edges,
    a resource collection with an entry, a corpus with a membership, an
    expression with a sub-expression and an annotation layer anchored to its
    text, plus standalone media, persona, and eprint records. A segmentation is
    included with no bespoke renderer so the generic fallback is exercised too.
    """
    repo = Repository.init(tmp_path / "repo")

    sentence = "The quick brown fox jumps."
    s1 = _uri("pub.layers.expression.expression", "s1")
    s2 = _uri("pub.layers.expression.expression", "s2")
    child = _uri("pub.layers.expression.expression", "s1a")
    repo.save(
        s1,
        expression.Expression(id="s1", kind="sentence", createdAt=_NOW, text=sentence),
    )
    repo.save(
        s2,
        expression.Expression(
            id="s2", kind="sentence", createdAt=_NOW, text="A brown dog runs."
        ),
    )
    repo.save(
        child,
        expression.Expression(
            id="s1a", kind="token", createdAt=_NOW, text="fox", parentRef=s1
        ),
    )

    onto = _uri("pub.layers.ontology.ontology", "ud")
    repo.save(
        onto,
        ontology.Ontology(
            name="Universal Dependencies",
            createdAt=_NOW,
            domain="syntax",
            version="2",
            description="A cross-linguistic dependency scheme.",
        ),
    )
    repo.save(
        _uri("pub.layers.ontology.typeDef", "nsubj"),
        ontology.TypeDef(
            name="nsubj",
            typeKind="relation",
            ontologyRef=onto,
            createdAt=_NOW,
            gloss="nominal subject",
        ),
    )
    repo.save(
        _uri("pub.layers.ontology.typeDef", "person"),
        ontology.TypeDef(
            name="Person", typeKind="entity", ontologyRef=onto, createdAt=_NOW
        ),
    )

    exp = _uri("pub.layers.judgment.experimentDef", "accept")
    repo.save(
        exp,
        judgment.ExperimentDef(
            name="Acceptability",
            createdAt=_NOW,
            measureType="acceptability",
            taskType="ordinal-scale",
            scaleMin=1,
            scaleMax=7,
        ),
    )
    repo.save(
        _uri("pub.layers.judgment.judgmentSet", "js1"),
        judgment.JudgmentSet(
            experimentRef=exp,
            createdAt=_NOW,
            agent=defs.AgentRef(name="annotator A"),
            judgments=(
                judgment.Judgment(
                    item=defs.ObjectRef(recordRef=s1), categoricalValue="yes"
                ),
                judgment.Judgment(
                    item=defs.ObjectRef(recordRef=s2), categoricalValue="no"
                ),
            ),
        ),
    )
    repo.save(
        _uri("pub.layers.judgment.agreementReport", "ar1"),
        judgment.AgreementReport(
            experimentRef=exp,
            createdAt=_NOW,
            metric="fleiss-kappa",
            value=820,
            numAnnotators=3,
        ),
    )

    edge = graph.GraphEdgeEntry(
        uuid=defs.Uuid(value="00000000-0000-0000-0000-000000000001"),
        source=defs.ObjectRef(recordRef=s1),
        target=defs.ObjectRef(recordRef=s2),
        edgeType="causal",
    )
    repo.save(
        _uri("pub.layers.graph.graphEdgeSet", "g1"),
        graph.GraphEdgeSet(edges=(edge,), createdAt=_NOW, edgeType="causal"),
    )

    col = _uri("pub.layers.resource.collection", "lexicon")
    entry = _uri("pub.layers.resource.entry", "run")
    repo.save(
        col,
        resource.Collection(
            name="Verb lexicon", createdAt=_NOW, kind="lexicon", version="1"
        ),
    )
    repo.save(
        entry,
        resource.Entry(
            form="run",
            createdAt=_NOW,
            components=(resource.MweComponent(form="run"),),
        ),
    )
    repo.save(
        _uri("pub.layers.resource.collectionMembership", "cm1"),
        resource.CollectionMembership(
            collectionRef=col, entryRef=entry, createdAt=_NOW
        ),
    )

    cor = _uri("pub.layers.corpus.corpus", "ewt")
    repo.save(
        cor,
        corpus.Corpus(
            name="English Web Treebank",
            createdAt=_NOW,
            domain="web",
            expressionCount=2,
            licensing=defs.Licensing(licenses=(defs.LicenseRef(spdx="CC-BY-SA-4.0"),)),
        ),
    )
    repo.save(
        _uri("pub.layers.corpus.membership", "m1"),
        corpus.Membership(
            corpusRef=cor, expressionRef=s1, createdAt=_NOW, split="train"
        ),
    )

    tok_id = "tok/s1/words"
    spans = [(0, 3), (4, 9), (10, 15), (16, 19), (20, 25), (25, 26)]
    forms = ["The", "quick", "brown", "fox", "jumps", "."]
    pos = ["DET", "ADJ", "ADJ", "NOUN", "VERB", "PUNCT"]
    heads = [3, 3, 3, 4, -1, 4]
    deprels = ["det", "amod", "amod", "nsubj", "root", "punct"]

    def _tok_ref(index: int) -> defs.Anchor:
        return defs.Anchor(
            tokenRef=defs.TokenRef(
                tokenIndex=index, tokenizationId=defs.Uuid(value=tok_id)
            )
        )

    repo.save(
        _uri("pub.layers.segmentation.segmentation", "seg1"),
        segmentation.Segmentation(
            expression=s1,
            createdAt=_NOW,
            tokenizations=(
                segmentation.Tokenization(
                    uuid=defs.Uuid(value=tok_id),
                    kind="penn-treebank",
                    tokens=tuple(
                        segmentation.Token(
                            tokenIndex=i,
                            text=forms[i],
                            textSpan=defs.Span(byteStart=a, byteEnd=b),
                        )
                        for i, (a, b) in enumerate(spans)
                    ),
                ),
            ),
        ),
    )
    repo.save(
        _uri("pub.layers.annotation.annotationLayer", "al1"),
        annotation.AnnotationLayer(
            expression=s1,
            kind="token-tag",
            subkind="pos",
            createdAt=_NOW,
            tokenizationId=defs.Uuid(value=tok_id),
            annotations=tuple(
                annotation.Annotation(
                    uuid=defs.Uuid(value=f"00000000-0000-0000-0000-0000000000a{i}"),
                    label=pos[i],
                    anchor=_tok_ref(i),
                )
                for i in range(len(forms))
            ),
        ),
    )
    repo.save(
        _uri("pub.layers.annotation.annotationLayer", "al2"),
        annotation.AnnotationLayer(
            expression=s1,
            kind="relation",
            subkind="dependency",
            createdAt=_NOW,
            tokenizationId=defs.Uuid(value=tok_id),
            annotations=tuple(
                annotation.Annotation(
                    uuid=defs.Uuid(value=f"00000000-0000-0000-0000-0000000000b{i}"),
                    label=deprels[i],
                    headIndex=heads[i],
                    anchor=_tok_ref(i),
                )
                for i in range(len(forms))
            ),
        ),
    )

    repo.save(
        _uri("pub.layers.media.media", "clip"),
        media.Media(
            kind="audio",
            createdAt=_NOW,
            title="field recording",
            mimeType="audio/wav",
            durationMs=5000,
        ),
    )
    repo.save(
        _uri("pub.layers.persona.persona", "expert"),
        persona.Persona(
            name="Syntax expert",
            createdAt=_NOW,
            domain="syntax",
            kind="human",
            guidelines="Annotate dependency relations.",
        ),
    )
    repo.save(
        _uri("pub.layers.eprint.eprint", "ud-paper"),
        eprint.Eprint(
            eprintIdentifier="10.5555/ud",
            eprintIdentifierType="doi",
            linkType="describes",
            createdAt=_NOW,
            citation=eprint.Citation(
                title="Universal Dependencies",
                doi="10.5555/ud",
                containerTitle="LREC",
                creators=(eprint.Creator(family="Nivre", given="Joakim"),),
            ),
        ),
    )

    return repo.path
