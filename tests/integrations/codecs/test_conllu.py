"""Unit and integration tests for lairs.integrations.codecs.conllu."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, override

import didactic.api as dx
import pytest
from hypothesis import strategies as st

if TYPE_CHECKING:
    from collections.abc import Callable

from lairs.integrations.codecs import CorpusFragment
from lairs.integrations.codecs.conllu import (
    ConlluCodec,
    ConlluIso,
    _ConlluSentence,
    _ConlluToken,
    _Feat,
    _MultiwordToken,
    _parse_conllu,
    _parse_with_library,
    _render_sentence,
    _segmentation_tokens,
)
from lairs.integrations.ports import Codec

# a small three-token sentence with pos, xpos, lemma, feats, and a dep tree.
_CONLLU = (
    "# text = The dog runs\n"
    "1\tThe\tthe\tDET\tDT\tDefinite=Def|PronType=Art\t2\tdet\t_\t_\n"
    "2\tdog\tdog\tNOUN\tNN\tNumber=Sing\t3\tnsubj\t_\t_\n"
    "3\truns\trun\tVERB\tVBZ\tNumber=Sing|Person=3\t0\troot\t_\t_\n"
)


def _sentence() -> _ConlluSentence:
    """Return the parsed form of the fixture sentence."""
    return _ConlluSentence(
        text="The dog runs",
        tokens=(
            _ConlluToken(
                index=0,
                form="The",
                lemma="the",
                upos="DET",
                xpos="DT",
                feats=(
                    _Feat(key="Definite", value="Def"),
                    _Feat(key="PronType", value="Art"),
                ),
                head=1,
                deprel="det",
            ),
            _ConlluToken(
                index=1,
                form="dog",
                lemma="dog",
                upos="NOUN",
                xpos="NN",
                feats=(_Feat(key="Number", value="Sing"),),
                head=2,
                deprel="nsubj",
            ),
            _ConlluToken(
                index=2,
                form="runs",
                lemma="run",
                upos="VERB",
                xpos="VBZ",
                feats=(
                    _Feat(key="Number", value="Sing"),
                    _Feat(key="Person", value="3"),
                ),
                head=-1,
                deprel="root",
            ),
        ),
    )


def test_name() -> None:
    assert ConlluCodec.name == "conllu"


def test_is_codec_protocol() -> None:
    assert isinstance(ConlluCodec(), Codec)


def test_importing_module_does_not_import_conllu(
    assert_lazy_import: Callable[..., None],
) -> None:
    assert_lazy_import("lairs.integrations.codecs.conllu", "conllu")


def test_decode_requires_optional_library(monkeypatch: pytest.MonkeyPatch) -> None:
    # simulate the optional library being absent so the error path is exercised
    # regardless of whether the dev environment has conllu installed.
    monkeypatch.setitem(sys.modules, "conllu", None)
    with pytest.raises(ModuleNotFoundError, match="conllu"):
        ConlluCodec().decode(_CONLLU)


def test_encode_requires_optional_library(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "conllu", None)
    with pytest.raises(ModuleNotFoundError, match="conllu"):
        ConlluCodec().encode([])


def test_parse_conllu_reads_columns() -> None:
    sentence = _parse_conllu(_CONLLU)
    assert sentence == _sentence()


def test_parse_conllu_falls_back_to_joined_forms() -> None:
    sentence = _parse_conllu("1\tHi\t_\t_\t_\t_\t_\t_\t_\t_\n")
    assert sentence.text == "Hi"


def test_parse_conllu_skips_multiword_tokens() -> None:
    src = (
        "1-2\tdon't\t_\t_\t_\t_\t_\t_\t_\t_\n"
        "1\tdo\t_\t_\t_\t_\t_\t_\t_\t_\n"
        "2\tn't\t_\t_\t_\t_\t_\t_\t_\t_\n"
    )
    sentence = _parse_conllu(src)
    assert [token.form for token in sentence.tokens] == ["do", "n't"]
    assert sentence.tokens[0].multiword == _MultiwordToken(
        start=0,
        end=1,
        form="don't",
    )
    assert sentence.tokens[1].multiword == sentence.tokens[0].multiword


def test_parse_with_library_retains_multiword_range() -> None:
    """The optional parser keeps range metadata for its component words."""
    conllu = pytest.importorskip("conllu")
    sentence = _parse_with_library(conllu, _CONLLU_MULTIWORD)[0]

    assert sentence.tokens[1].multiword == _MultiwordToken(
        start=1,
        end=2,
        form="zur",
    )
    assert sentence.tokens[2].multiword == sentence.tokens[1].multiword


def test_render_sentence_round_trips_parse() -> None:
    sentence = _sentence()
    assert _parse_conllu(_render_sentence(sentence)) == sentence


def test_iso_forward_builds_expected_layers() -> None:
    fragment = ConlluIso().forward(_sentence())
    locals_ = [record.local_id for record in fragment.records]
    assert locals_ == [
        "expression",
        "segmentation",
        "upos",
        "xpos",
        "lemma",
        "dependencies",
    ]


def test_iso_dependency_layer_carries_head_indices() -> None:
    fragment = ConlluIso().forward(_sentence())
    deps = next(r for r in fragment.records if r.local_id == "dependencies")
    layer = json.loads(deps.value_json)
    heads = [a["headIndex"] for a in layer["annotations"]]
    assert heads == [1, 2, -1]


def test_iso_token_tag_layer_uses_token_anchor() -> None:
    fragment = ConlluIso().forward(_sentence())
    upos = next(r for r in fragment.records if r.local_id == "upos")
    layer = json.loads(upos.value_json)
    first = layer["annotations"][0]
    assert first["anchor"]["tokenRef"]["tokenIndex"] == 0
    assert first["label"] == "DET"


def test_iso_segmentation_byte_offsets_track_the_text() -> None:
    # every token's textSpan must slice the expression text back to its form,
    # so a non-first token has byteStart > 0 (not the old all-zero offset bug).
    fragment = ConlluIso().forward(_sentence())
    seg = next(r for r in fragment.records if r.local_id == "segmentation")
    tokens = json.loads(seg.value_json)["tokenizations"][0]["tokens"]
    text = b"The dog runs"
    starts = []
    for token in tokens:
        span = token["textSpan"]
        starts.append(span["byteStart"])
        sliced = text[span["byteStart"] : span["byteEnd"]].decode()
        assert sliced == token["text"]
    assert starts == [0, 4, 8]


def test_iso_backward_recovers_sentence() -> None:
    iso = ConlluIso()
    assert iso.backward(iso.forward(_sentence())) == _sentence()


def test_iso_omits_dependency_layer_when_no_heads() -> None:
    sentence = _ConlluSentence(
        text="Hi there",
        tokens=(
            _ConlluToken(index=0, form="Hi", upos="INTJ"),
            _ConlluToken(index=1, form="there", upos="ADV"),
        ),
    )
    fragment = ConlluIso().forward(sentence)
    locals_ = [record.local_id for record in fragment.records]
    assert "dependencies" not in locals_


@st.composite
def _sentences(draw: st.DrawFn) -> _ConlluSentence:
    """Draw a small CoNLL-U sentence with a valid dependency tree."""
    forms = st.text(alphabet="abcdefg", min_size=1, max_size=5)
    tags = st.sampled_from(["NOUN", "VERB", "DET", "ADJ", "ADV"])
    count = draw(st.integers(min_value=1, max_value=5))
    tokens: list[_ConlluToken] = []
    for index in range(count):
        # a projective tree: each non-root token attaches to a lower index.
        head = -1 if index == 0 else draw(st.integers(min_value=0, max_value=index - 1))
        tokens.append(
            _ConlluToken(
                index=index,
                form=draw(forms),
                lemma=draw(forms),
                upos=draw(tags),
                xpos=draw(tags),
                feats=draw(
                    st.lists(
                        st.builds(
                            _Feat,
                            key=st.sampled_from(["Number", "Tense", "Case"]),
                            value=st.sampled_from(["Sing", "Plur", "Past"]),
                        ),
                        max_size=2,
                    ).map(tuple)
                ),
                head=head,
                deprel="root" if head == -1 else "dep",
            )
        )
    text = " ".join(token.form for token in tokens)
    return _ConlluSentence(text=text, tokens=tuple(tokens))


def test_iso_law_property() -> None:
    dx.testing.verify_iso(_RoundTripIso(), _sentences(), max_examples=50)


class _RoundTripIso(dx.Iso[_ConlluSentence, _ConlluSentence]):
    """Compose the conllu Iso with its inverse for ``verify_iso``."""

    @override
    def forward(self, a: _ConlluSentence, /) -> _ConlluSentence:
        iso = ConlluIso()
        return iso.backward(iso.forward(a))

    @override
    def backward(self, b: _ConlluSentence, /) -> _ConlluSentence:
        return b


# a two-sentence treebank fragment used to exercise multi-sentence decoding.
_CONLLU_MULTI = (
    "# text = The dog runs\n"
    "1\tThe\tthe\tDET\tDT\t_\t2\tdet\t_\t_\n"
    "2\tdog\tdog\tNOUN\tNN\t_\t3\tnsubj\t_\t_\n"
    "3\truns\trun\tVERB\tVBZ\t_\t0\troot\t_\t_\n"
    "\n"
    "# text = Cats sleep\n"
    "1\tCats\tcat\tNOUN\tNNS\t_\t2\tnsubj\t_\t_\n"
    "2\tsleep\tsleep\tVERB\tVBP\t_\t0\troot\t_\t_\n"
)


def test_codec_decode_uses_library_and_builds_layers() -> None:
    # decode/encode go through the conllu library; exercise them in the default
    # suite (not only the integration job) so a regression is caught early.
    pytest.importorskip("conllu")
    fragment = ConlluCodec().decode(_CONLLU)
    assert isinstance(fragment, CorpusFragment)
    locals_ = [record.local_id for record in fragment.records]
    assert locals_ == [
        "expression",
        "segmentation",
        "upos",
        "xpos",
        "lemma",
        "dependencies",
    ]


def test_codec_round_trips_through_library() -> None:
    pytest.importorskip("conllu")
    codec = ConlluCodec()
    fragment = codec.decode(_CONLLU)
    reparsed = codec.decode(codec.encode(fragment.records))
    assert reparsed == fragment


def test_codec_encode_returns_str() -> None:
    pytest.importorskip("conllu")
    codec = ConlluCodec()
    fragment = codec.decode(_CONLLU)
    assert isinstance(codec.encode(fragment.records), str)


def test_codec_decodes_every_sentence() -> None:
    # a multi-sentence file must not silently drop sentences after the first.
    pytest.importorskip("conllu")
    fragment = ConlluCodec().decode(_CONLLU_MULTI)
    locals_ = [record.local_id for record in fragment.records]
    assert "expression" in locals_
    assert "expression-1" in locals_
    expressions = [
        json.loads(r.value_json)["text"]
        for r in fragment.records
        if r.local_id in {"expression", "expression-1"}
    ]
    assert expressions == ["The dog runs", "Cats sleep"]


def test_codec_multi_sentence_round_trips() -> None:
    pytest.importorskip("conllu")
    codec = ConlluCodec()
    fragment = codec.decode(_CONLLU_MULTI)
    reparsed = codec.decode(codec.encode(fragment.records))
    assert reparsed == fragment


def test_codec_into_extends_across_sentences() -> None:
    pytest.importorskip("conllu")
    codec = ConlluCodec()
    first = codec.decode(_CONLLU)
    second = codec.decode(_CONLLU_MULTI, into=first)
    assert len(second.records) == len(first.records) + len(
        codec.decode(_CONLLU_MULTI).records
    )


@pytest.mark.integration
def test_codec_round_trip_live() -> None:
    pytest.importorskip("conllu")
    codec = ConlluCodec()
    fragment = codec.decode(_CONLLU)
    assert isinstance(fragment, CorpusFragment)
    reparsed = codec.decode(codec.encode(fragment.records))
    assert reparsed == fragment


# a sentence whose declared text runs tokens together, as UD corpora do.
_CONLLU_NO_SPACE_AFTER = (
    "# text = Al-Zaman : American forces\n"
    "1\tAl\tAl\tPROPN\tNNP\t_\t0\troot\t_\tSpaceAfter=No\n"
    "2\t-\t-\tPUNCT\tHYPH\t_\t3\tpunct\t_\tSpaceAfter=No\n"
    "3\tZaman\tZaman\tPROPN\tNNP\t_\t1\tflat\t_\t_\n"
    "4\t:\t:\tPUNCT\t:\t_\t6\tpunct\t_\t_\n"
    "5\tAmerican\tAmerican\tADJ\tJJ\t_\t6\tamod\t_\t_\n"
    "6\tforces\tforce\tNOUN\tNNS\t_\t1\tnsubj\t_\t_\n"
)

_CONLLU_MULTIWORD = (
    "# text = Über zur Schule\n"
    "1\tÜber\tüber\tADP\t_\t_\t4\tcase\t_\t_\n"
    "2-3\tzur\t_\t_\t_\t_\t_\t_\t_\t_\n"
    "2\tzu\tzu\tADP\t_\t_\t4\tcase\t_\t_\n"
    "3\tder\tder\tDET\t_\t_\t4\tdet\t_\t_\n"
    "4\tSchule\tSchule\tNOUN\t_\t_\t0\troot\t_\t_\n"
)


def test_every_token_span_slices_the_declared_text_back_to_its_form() -> None:
    """A span indexes the text the sentence declares, not a space-joined one."""
    sentence = _parse_conllu(_CONLLU_NO_SPACE_AFTER)
    encoded = sentence.text.encode("utf-8")

    for token in _segmentation_tokens(sentence):
        span = token.textSpan

        assert span is not None
        assert encoded[span.byteStart : span.byteEnd].decode("utf-8") == token.text


def test_no_token_span_runs_past_the_declared_text() -> None:
    """Spans stay inside the text, which a space-joined cursor would not."""
    sentence = _parse_conllu(_CONLLU_NO_SPACE_AFTER)
    limit = len(sentence.text.encode("utf-8"))

    for token in _segmentation_tokens(sentence):
        assert token.textSpan is not None
        assert token.textSpan.byteEnd <= limit


def test_multiword_components_share_the_range_surface_span() -> None:
    """Syntactic words in a multiword token point at its whole surface form."""
    sentence = _parse_conllu(_CONLLU_MULTIWORD)
    tokens = tuple(_segmentation_tokens(sentence))
    spans = []
    for token in tokens:
        assert token.textSpan is not None
        spans.append((token.textSpan.byteStart, token.textSpan.byteEnd))

    assert spans == [
        (0, 5),
        (6, 9),
        (6, 9),
        (10, 16),
    ]
    assert sentence.text.encode("utf-8")[6:9].decode("utf-8") == "zur"


def test_multiword_sentence_round_trips_through_layers_records() -> None:
    """Shared spans preserve range rows through the Layers representation."""
    sentence = _parse_conllu(_CONLLU_MULTIWORD)
    iso = ConlluIso()

    assert iso.backward(iso.forward(sentence)) == sentence


def test_render_sentence_emits_multiword_range_row() -> None:
    """Rendering restores the range row before its component words."""
    sentence = _parse_conllu(_CONLLU_MULTIWORD)

    assert "2-3\tzur\t_\t_\t_\t_\t_\t_\t_\t_\n2\tzu" in _render_sentence(sentence)


def test_codec_round_trips_multiword_range() -> None:
    """The optional library path preserves a multiword range on encoding."""
    pytest.importorskip("conllu")
    codec = ConlluCodec()

    fragment = codec.decode(_CONLLU_MULTIWORD)
    encoded = codec.encode(fragment.records)

    assert "2-3\tzur\t_\t_\t_\t_\t_\t_\t_\t_\n2\tzu" in encoded
    assert codec.decode(encoded) == fragment


def test_unalignable_form_has_no_fabricated_span() -> None:
    """A conflicting declared text produces an absent span, never overflow."""
    sentence = _parse_conllu("# text = short\n1\tlonger\t_\t_\t_\t_\t_\t_\t_\t_\n")

    assert next(iter(_segmentation_tokens(sentence))).textSpan is None
