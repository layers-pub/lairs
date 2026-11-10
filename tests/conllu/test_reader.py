"""Unit tests for lairs.conllu.reader."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from lairs.conllu.projection import Projector
from lairs.conllu.reader import sentences, sentences_from_json
from lairs.conllu.text import parse, serialize
from lairs.data.corpus import Corpus
from lairs.store.pool import ModelPool

if TYPE_CHECKING:
    from lairs._types import JsonValue

_DOC = (
    "# newdoc id = d1\n"
    "# sent_id = a\n"
    "# text = zur Schule\n"
    "1-2\tzur\t_\t_\t_\t_\t_\t_\t_\t_\n"
    "1\tzu\tzu\tADP\t_\t_\t3\tcase\t3:case\t_\n"
    "2\tder\tder\tDET\t_\tCase=Dat\t3\tdet\t3:det\t_\n"
    "3\tSchule\tSchule\tNOUN\t_\t_\t0\troot\t0:root\tSpaceAfter=No\n"
    "3.1\tgeht\t_\t_\t_\t_\t_\t_\t3:conj\tE=1\n"
    "\n"
    "# sent_id = b\n"
    "# text = ja\n"
    "1\tja\tja\tINTJ\t_\t_\t0\troot\t_\t_\n"
    "\n"
    "# newdoc id = d2\n"
    "# sent_id = c\n"
    "# text = nein\n"
    "1\tnein\tnein\tINTJ\t_\t_\t0\troot\t_\t_\n"
    "\n"
)

_CORPUS = "at://did:plc:corpus/pub.layers.corpus.corpus/ud"


def _mapping(
    text: str = _DOC,
    projector: Projector | None = None,
) -> dict[str, JsonValue]:
    """Project ``text`` into a raw AT-URI to JSON mapping."""
    records = (projector or Projector()).project(parse(text))
    return {record.uri: record.value() for record in records}


def test_reads_a_raw_mapping_exactly() -> None:
    read = list(sentences(_mapping()))
    assert serialize(read) == _DOC
    assert [s.sent_id for s in read] == ["a", "b", "c"]
    assert all(s.exact for s in read)


def test_reads_a_corpus_of_models() -> None:
    pool = ModelPool()
    for record in Projector().project(parse(_DOC)):
        pool.add(record.uri, record.to_model())
    assert serialize(sentences(Corpus(pool))) == _DOC


def test_membership_order_and_split() -> None:
    projector = Projector(corpus_ref=_CORPUS, split="test")
    mapping = _mapping(projector=projector)
    shuffled = dict(reversed(list(mapping.items())))
    assert serialize(sentences(shuffled)) == _DOC
    assert serialize(sentences(shuffled, split="test")) == _DOC
    assert list(sentences(shuffled, split="train")) == []
    assert (
        list(sentences(shuffled, corpus="at://other/pub.layers.corpus.corpus/x")) == []
    )
    assert len(list(sentences(shuffled, corpus=_CORPUS))) == 3


def test_corpus_selection_by_uri() -> None:
    mapping = _mapping(projector=Projector(corpus_ref=_CORPUS))
    other_text = "# sent_id = z\n1\tz\t_\tX\t_\t_\t0\troot\t_\t_\n\n"
    other = Projector(
        corpus_ref="at://did:plc:corpus/pub.layers.corpus.corpus/other",
    )
    for record in other.project(parse(other_text), start=10):
        mapping[record.uri] = record.value()
    assert [s.sent_id for s in sentences(mapping, corpus=_CORPUS)] == ["a", "b", "c"]
    pool = ModelPool()
    for record in Projector(corpus_ref=_CORPUS).project(parse(_DOC)):
        pool.add(record.uri, record.to_model())
    for record in other.project(parse(other_text), start=10):
        pool.add(record.uri, record.to_model())
    assert [s.sent_id for s in sentences(Corpus(pool, uri=_CORPUS))] == ["a", "b", "c"]
    assert len(list(sentences(Corpus(pool)))) == 4


def test_split_without_memberships_yields_nothing() -> None:
    assert list(sentences(_mapping(), split="dev")) == []


def test_type_key_classifies_records_with_local_uris() -> None:
    raw: dict[str, JsonValue] = {}
    for index, record in enumerate(Projector().project(parse(_DOC))):
        value = record.value()
        value["$type"] = record.nsid
        raw[f"at://local/{index}"] = value
    raw["at://local/junk"] = ["not", "a", "record"]
    # references still point at the projector's uris, so rewrite them.
    renamed = {
        record.uri: f"at://local/{i}"
        for i, record in enumerate(Projector().project(parse(_DOC)))
    }
    text = json.dumps(raw)
    for old, new in renamed.items():
        text = text.replace(json.dumps(old), json.dumps(new))
    loaded = json.loads(text)
    assert serialize(sentences(loaded)) == _DOC


def test_core_accepts_triples() -> None:
    triples = [(r.uri, r.nsid, r.value()) for r in Projector().project(parse(_DOC))]
    assert serialize(sentences_from_json(triples)) == _DOC


# records shaped like the Layers UD importer's current output: no carriers,
# real AT-URIs spread over expression, segmentation, annotation, and alignment
# accounts, explicit nulls, and $type keys.
_EXPR = "at://did:plc:expr/pub.layers.expression.expression"
_SEG = "at://did:plc:seg/pub.layers.segmentation.segmentation"
_ANN = "at://did:plc:ann/pub.layers.annotation.annotationLayer"
_ALN = "at://did:plc:aln/pub.layers.alignment.alignment"
_MEM = "at://did:plc:corpus/pub.layers.corpus.membership"
_STAMP = "2024-01-01T00:00:00.000Z"


def _token(index: int, text: str, span: tuple[int, int] | None) -> JsonValue:
    """Return a wire-shaped token."""
    return {
        "$type": "pub.layers.segmentation.defs#token",
        "tokenIndex": index,
        "text": text,
        "textSpan": None
        if span is None
        else {"byteStart": span[0], "byteEnd": span[1]},
        "temporalSpan": None,
    }


def _tag(index: int, label: str, uuid: str, **extra: JsonValue) -> JsonValue:
    """Return a wire-shaped token-tag annotation."""
    value: dict[str, JsonValue] = {
        "uuid": {"value": f"x-{index}"},
        "anchor": {
            "tokenRef": {"tokenIndex": index, "tokenizationId": {"value": uuid}}
        },
        "tokenIndex": index,
        "label": label,
        "value": None,
        "headIndex": None,
        "features": None,
    }
    value.update(extra)
    return value


def _layer(subkind: str, uuid: str, annotations: list[JsonValue]) -> JsonValue:
    """Return a wire-shaped annotation layer on sentence ``a``."""
    return {
        "$type": "pub.layers.annotation.annotationLayer",
        "expression": f"{_EXPR}/a",
        "kind": "relation" if "dependency" in subkind else "token-tag",
        "subkind": subkind,
        "formalism": "universal-dependencies",
        "tokenizationId": {"value": uuid},
        "annotations": annotations,
        "createdAt": _STAMP,
        "parentLayerRef": None,
    }


def _feats(*pairs: tuple[str, str]) -> JsonValue:
    """Return a wire-shaped feature map."""
    return {"entries": [{"key": k, "value": v} for k, v in pairs]}


def _published() -> dict[str, JsonValue]:
    """Return sentence ``a`` of ``_DOC`` as the importer publishes it."""
    words = "ud/a/words"
    enhanced = "ud/a/enhanced"
    return {
        f"{_EXPR}/doc": {
            "$type": "pub.layers.expression.expression",
            "id": "d1",
            "kind": "document",
            "text": None,
            "parentRef": None,
            "createdAt": _STAMP,
        },
        f"{_EXPR}/a": {
            "$type": "pub.layers.expression.expression",
            "id": "a",
            "kind": "sentence",
            "text": "zur Schule",
            "parentRef": f"{_EXPR}/doc",
            "features": None,
            "createdAt": _STAMP,
        },
        f"{_MEM}/a": {
            "corpusRef": _CORPUS,
            "expressionRef": f"{_EXPR}/a",
            "ordinal": 0,
            "split": "test",
            "createdAt": _STAMP,
        },
        f"{_SEG}/a": {
            "expression": f"{_EXPR}/a",
            "createdAt": _STAMP,
            "tokenizations": [
                {
                    "kind": "custom",
                    "uuid": {"value": "ud/a/surface"},
                    "tokens": [_token(0, "zur", (0, 3)), _token(1, "Schule", (4, 10))],
                },
                {
                    "kind": "custom",
                    "uuid": {"value": words},
                    "tokens": [
                        _token(0, "zu", (0, 3)),
                        _token(1, "der", (0, 3)),
                        _token(2, "Schule", (4, 10)),
                    ],
                },
            ],
        },
        f"{_SEG}/a-enhanced": {
            "expression": f"{_EXPR}/a",
            "createdAt": _STAMP,
            "tokenizations": [
                {
                    "kind": "custom",
                    "uuid": {"value": enhanced},
                    "tokens": [
                        _token(0, "zu", (0, 3)),
                        _token(1, "der", (0, 3)),
                        _token(2, "Schule", (4, 10)),
                        _token(3, "geht", None),
                    ],
                }
            ],
        },
        f"{_ALN}/a": {
            "expression": f"{_EXPR}/a",
            "kind": "tokenization-to-tokenization",
            "subkind": "word-to-word",
            "source": {"localId": {"value": "ud/a/surface"}, "recordRef": None},
            "target": {"localId": {"value": words}, "recordRef": None},
            "links": [
                {
                    "sourceIndices": [0],
                    "targetIndices": [0, 1],
                    "label": "multiword-token",
                    "features": None,
                },
                {
                    "sourceIndices": [1],
                    "targetIndices": [2],
                    "label": "one-to-one",
                    "features": None,
                },
            ],
            "createdAt": _STAMP,
        },
        f"{_ANN}/upos": _layer(
            "pos",
            words,
            [_tag(0, "ADP", words), _tag(1, "DET", words), _tag(2, "NOUN", words)],
        ),
        f"{_ANN}/lemma": _layer(
            "lemma",
            words,
            [
                _tag(0, "zu", words, value="zu"),
                _tag(1, "der", words, value="der"),
                _tag(2, "Schule", words, value="Schule"),
            ],
        ),
        f"{_ANN}/morph": _layer("morph", words, [_tag(1, "Case=Dat", words)]),
        f"{_ANN}/deps": _layer(
            "dependency",
            words,
            [
                _tag(
                    0,
                    "case",
                    words,
                    headIndex=2,
                    features=_feats(("ud_relation", "case")),
                ),
                _tag(
                    1,
                    "det",
                    words,
                    headIndex=2,
                    features=_feats(("ud_relation", "det")),
                ),
                _tag(
                    2,
                    "root",
                    words,
                    headIndex=-1,
                    features=_feats(("ud_relation", "root")),
                ),
            ],
        ),
        f"{_ANN}/edeps": _layer(
            "enhanced-dependency",
            enhanced,
            [
                _tag(
                    0,
                    "case",
                    enhanced,
                    headIndex=2,
                    targetIndex=0,
                    features=_feats(("isEnhanced", "true")),
                ),
                _tag(
                    1,
                    "det",
                    enhanced,
                    headIndex=2,
                    targetIndex=1,
                    features=_feats(("isEnhanced", "true")),
                ),
                _tag(
                    2,
                    "root",
                    enhanced,
                    headIndex=-1,
                    targetIndex=2,
                    features=_feats(("isEnhanced", "true")),
                ),
                _tag(
                    3,
                    "conj",
                    enhanced,
                    headIndex=2,
                    targetIndex=3,
                    features=_feats(("isEnhanced", "true"), ("ud_empty_node", "3.1")),
                ),
            ],
        ),
    }


def test_reads_importer_shaped_records_and_flags_losses() -> None:
    (sentence,) = sentences(_published(), corpus=_CORPUS)
    assert set(sentence.lossy) == {
        "comments",
        "misc",
        "feats",
        "empty_nodes",
        "multiword_tokens",
    }
    assert sentence.comment_lines == (
        "# newdoc id = d1",
        "# sent_id = a",
        "# text = zur Schule",
    )
    expected = "".join(
        _DOC.split("\n\n", maxsplit=1)[0].split("\n# text = zur Schule\n")[1:]
    )
    rows = expected.replace("\tE=1", "\t_").replace("SpaceAfter=No", "_")
    assert "\n".join(sentence.row_lines) == rows
    # SpaceAfter=No on the last word cannot be inferred and is not invented.
    assert sentence.rows[-2].misc == ()


def test_reads_importer_shaped_records_without_alignment() -> None:
    records = {k: v for k, v in _published().items() if not k.startswith(_ALN)}
    (sentence,) = sentences(records)
    assert sentence.row_lines[0] == "1-2\tzur\t_\t_\t_\t_\t_\t_\t_\t_"
