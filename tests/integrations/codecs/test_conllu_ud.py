"""Unit and integration tests for lairs.integrations.codecs.conllu_ud."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import override

import didactic.api as dx
import pytest
from hypothesis import strategies as st

from lairs.conllu import sentences
from lairs.conllu.model import ConlluSentence
from lairs.conllu.projection import (
    ALIGNMENT_NSID,
    ANNOTATION_NSID,
    EXPRESSION_NSID,
    SEGMENTATION_NSID,
)
from lairs.conllu.text import parse, serialize
from lairs.data.corpus import Corpus
from lairs.integrations.codecs import CorpusFragment
from lairs.integrations.codecs.conllu_ud import UdConlluCodec, UdConlluIso
from lairs.integrations.ports import Codec
from lairs.records._generated.alignment import Alignment
from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.expression import Expression
from lairs.records._generated.segmentation import Segmentation
from lairs.store.pool import ModelPool

# the environment variable naming a directory of real CoNLL-U treebanks.
_UD_DIR = "LAIRS_UD_DIR"

_DOC = (
    "# newdoc id = doc1\n"
    "# newpar id = par1\n"
    "# sent_id = s1\n"
    "# text = Über zur Schule…\n"
    "#  odd spacing =  kept  \n"
    "# free text without an equals sign\n"
    "1\tÜber\tüber\tADP\tAPPR\t_\t4\tcase\t4:case\tZ=1|Bare|A=2|A=3\n"
    "2-3\tzur\t_\t_\t_\tTypo=Yes\t_\t_\t_\tMwt=1|SpaceAfter=No|Mwt=2\n"
    "2\tzu\tzu\tADP\tAPPR\tNumber[psor]=Sing|Case=Acc,Dat\t4\tcase\t4:case|4.1:dep\t_\n"
    "3\tder\tder\tDET\tART\t_\t4\tdet\t4:det\t_\n"
    "4\tSchule\tSchule\tNOUN\tNN\tGender=Fem\t0\troot\t0:root|4.1:nsubj\tSpaceAfter=No\n"
    "4.1\tgeht\tgehen\tVERB\tVVFIN\tMood=Ind\t_\t_\t4:conj|0:root\tGloss=go\n"
    "5\t…\t…\tPUNCT\t$.\t_\t4\tpunct\t4:punct\t_\n"
    "\n"
    "# newpar\n"
    "1\t_\t_\tPUNCT\t_\t_\t0\troot\t0:root\t_\n"
    "\n"
    "# newdoc id = doc2\n"
    "# sent_id = s3\n"
    "1\tx\tx\tX\t_\t_\t_\t_\t_\tNote=1\n"
    "\n"
)


def test_codec_satisfies_the_port() -> None:
    codec = UdConlluCodec()
    assert isinstance(codec, Codec)
    assert codec.name == "conllu-ud"


def test_decode_encode_is_byte_exact() -> None:
    codec = UdConlluCodec()
    fragment = codec.decode(_DOC)
    assert fragment.source == "conllu-ud"
    assert codec.encode(fragment.records) == _DOC
    assert codec.encode(codec.decode(_DOC.encode("utf-8")).records) == _DOC


def test_fragment_reads_back_through_a_corpus_of_models() -> None:
    fragment = UdConlluCodec().decode(_DOC)
    models: dict[str, type[Expression | Segmentation | AnnotationLayer | Alignment]] = {
        EXPRESSION_NSID: Expression,
        SEGMENTATION_NSID: Segmentation,
        ANNOTATION_NSID: AnnotationLayer,
        ALIGNMENT_NSID: Alignment,
    }
    pool = ModelPool()
    for record in fragment.records:
        assert record.local_id.startswith(f"at://local/{record.nsid}/")
        pool.add(
            record.local_id, models[record.nsid].model_validate_json(record.value_json)
        )
    assert serialize(sentences(Corpus(pool))) == _DOC


def test_into_continues_ordinals() -> None:
    codec = UdConlluCodec()
    first = codec.decode(_DOC)
    both = codec.decode(_DOC, into=first)
    uris = [record.local_id for record in both.records]
    assert len(uris) == len(set(uris))
    assert codec.encode(both.records) == _DOC + _DOC


def test_typed_sentences_both_ways() -> None:
    codec = UdConlluCodec()
    sentences = list(codec.sentences(codec.decode(_DOC).records))
    assert [s.sent_id for s in sentences] == ["s1", None, "s3"]
    assert codec.encode_sentences(sentences) == _DOC
    assert codec.encode(codec.decode_sentences(sentences).records) == _DOC


def test_configured_codec_stamps_records() -> None:
    stamp = datetime(2020, 1, 2, tzinfo=UTC)
    codec = UdConlluCodec(
        created_at=stamp,
        languages=["de"],
        corpus_ref="at://did:plc:c/pub.layers.corpus.corpus/x",
        split="train",
    )
    fragment = codec.decode(_DOC)
    expression = json.loads(fragment.records[2].value_json)
    assert expression["createdAt"] == stamp.isoformat()
    assert expression["languages"] == ["de"]
    assert any(
        json.loads(r.value_json).get("split") == "train" for r in fragment.records
    )
    assert codec.encode(fragment.records) == _DOC


def test_iso_backward_rejects_an_empty_fragment() -> None:
    with pytest.raises(ValueError, match="no sentence"):
        UdConlluIso().backward(CorpusFragment())


_FORM = st.text(
    alphabet=st.characters(
        blacklist_characters="\t\n\r|",
        blacklist_categories=("Cs", "Zl", "Zp", "Cc"),
    ),
    min_size=1,
    max_size=5,
).filter(lambda s: s.strip() == s and s != "_")
_MISC = st.lists(
    st.one_of(
        _FORM.filter(lambda s: "=" not in s),
        st.tuples(_FORM.filter(lambda s: "=" not in s), _FORM).map("=".join),
        st.just("SpaceAfter=No"),
    ),
    max_size=3,
).map(lambda items: "|".join(items) or "_")


@st.composite
def _sentence(draw: st.DrawFn) -> ConlluSentence:
    """Draw a sentence with ranges, empty nodes, DEPS, FEATS, and free MISC."""
    count = draw(st.integers(min_value=1, max_value=5))
    rows: list[str] = []
    has_range = count >= 2 and draw(st.booleans())
    has_empty = draw(st.booleans())
    for word in range(1, count + 1):
        if has_range and word == 1:
            rows.append(f"1-2\t{draw(_FORM)}\t_\t_\t_\t_\t_\t_\t_\t{draw(_MISC)}")
        head = draw(st.integers(min_value=0, max_value=count))
        feats = draw(
            st.sampled_from(["_", "Case=Acc,Dat", "Number[psor]=Sing|Case=Nom"])
        )
        deps = f"{head}:dep" if draw(st.booleans()) else "_"
        if has_empty and word == 1 and deps != "_":
            deps = f"{deps}|1.1:orphan"
        rows.append(
            f"{word}\t{draw(_FORM)}\t{draw(_FORM)}\tX\t_\t{feats}\t{head}\tdep\t{deps}\t{draw(_MISC)}"
        )
        if has_empty and word == 1:
            rows.append(
                f"1.1\t{draw(_FORM)}\tl\tVERB\t_\tMood=Ind\t_\t_\t1:conj\t{draw(_MISC)}"
            )
    comments = [f"# sent_id = {draw(_FORM)}"] if draw(st.booleans()) else []
    comments.extend(f"#{draw(_FORM)}" for _ in range(draw(st.integers(0, 2))))
    return ConlluSentence.build(comments, rows)


def test_iso_laws() -> None:
    dx.testing.verify_iso(_RoundTripIso(), _sentence(), max_examples=60)


class _RoundTripIso(dx.Iso[ConlluSentence, ConlluSentence]):
    """Compose the codec Iso with its inverse for ``verify_iso``."""

    @override
    def forward(self, a: ConlluSentence, /) -> ConlluSentence:
        iso = UdConlluIso()
        return iso.backward(iso.forward(a))

    @override
    def backward(self, b: ConlluSentence, /) -> ConlluSentence:
        return b


def _treebank_files() -> list[Path]:
    """Return the treebank files under ``LAIRS_UD_DIR``, or skip."""
    root = os.environ.get(_UD_DIR)
    if not root:
        pytest.skip(f"set {_UD_DIR} to a directory of CoNLL-U treebanks")
    files = sorted(Path(root).rglob("*.conllu"))
    if not files:
        pytest.skip(f"no .conllu files under {root}")
    return files


@pytest.mark.integration
def test_real_treebanks_round_trip_exactly() -> None:
    codec = UdConlluCodec()
    for path in _treebank_files():
        text = path.read_text(encoding="utf-8")
        canonical = serialize(parse(text))
        assert canonical == text, f"text round trip differs for {path}"
        assert codec.encode(codec.decode(text).records) == text, path
