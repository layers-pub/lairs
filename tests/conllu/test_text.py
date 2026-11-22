"""Unit tests for lairs.conllu.text."""

from __future__ import annotations

import io

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lairs.conllu.model import ConlluSentence
from lairs.conllu.text import (
    ConlluSyntaxError,
    dump,
    parse,
    serialize,
    serialize_sentence,
)

# a document exercising every construct the format has.
_DOC = (
    "# newdoc id = doc1\n"
    "# newpar id = par1\n"
    "# sent_id = s1\n"
    "# text = Über zur Schule…\n"
    "#  odd spacing =  kept  \n"
    "# free text without an equals sign\n"
    "1\tÜber\tüber\tADP\tAPPR\t_\t4\tcase\t4:case\tZ=1|Bare|A=2|A=3\n"
    "2-3\tzur\t_\t_\t_\tTypo=Yes\t_\t_\t_\tMwt=1\n"
    "2\tzu\tzu\tADP\tAPPR\tNumber[psor]=Sing|Case=Acc,Dat\t4\tcase\t4:case|4.1:dep\t_\n"
    "3\tder\tder\tDET\tART\t_\t4\tdet\t4:det\t_\n"
    "4\tSchule\tSchule\tNOUN\tNN\tGender=Fem\t0\troot\t0:root\tSpaceAfter=No\n"
    "4.1\tgeht\tgehen\tVERB\tVVFIN\tMood=Ind\t_\t_\t4:conj|0:root\tGloss=go\n"
    "5\t…\t…\tPUNCT\t$.\t_\t4\tpunct\t4:punct\t_\n"
    "\n"
    "# newpar\n"
    "1\t_\t_\tPUNCT\t_\t_\t0\troot\t0:root\t_\n"
    "\n"
)


def test_round_trip_is_byte_exact() -> None:
    sentences = list(parse(_DOC))
    assert len(sentences) == 2
    assert serialize(sentences) == _DOC


def test_parse_accepts_lines_and_files() -> None:
    assert list(parse(io.StringIO(_DOC))) == list(parse(_DOC))
    assert list(parse(_DOC.splitlines(keepends=True))) == list(parse(_DOC))


@pytest.mark.parametrize(
    "variant",
    [
        _DOC.replace("\n", "\r\n"),
        "﻿" + _DOC,
        "\n\n" + _DOC.replace("\n\n#", "\n\n \n\n#"),
        _DOC.removesuffix("\n"),
        _DOC.removesuffix("\n\n"),
    ],
)
def test_framing_is_the_only_normalisation(variant: str) -> None:
    assert serialize(parse(variant)) == _DOC


def test_parse_streams() -> None:
    sentences = parse(_DOC + "bad line\n")
    assert next(sentences).sent_id == "s1"
    assert next(sentences).sent_id is None
    with pytest.raises(ConlluSyntaxError):
        next(sentences)


@pytest.mark.parametrize(
    ("source", "line", "message"),
    [
        ("# c\n1\tx\t_\n", 2, "expected 10"),
        ("1\tx\t_\t_\t_\t_\t0\troot\t_\t_\n# late\n", 2, "comment after"),
        ("# only\n# comments\n", 2, "no rows"),
        ("\n\n1\tx\t_\t_\t_\t_\tq\troot\t_\t_\n", 3, "malformed HEAD"),
    ],
)
def test_malformed_input_names_its_line(source: str, line: int, message: str) -> None:
    with pytest.raises(ConlluSyntaxError, match=message) as caught:
        list(parse(source))
    assert caught.value.line == line
    assert str(caught.value).startswith(f"line {line}: ")


def test_serialize_sentence_and_dump() -> None:
    sentences = list(parse(_DOC))
    assert (
        serialize_sentence(sentences[1])
        == "# newpar\n1\t_\t_\tPUNCT\t_\t_\t0\troot\t0:root\t_\n\n"
    )
    handle = io.StringIO()
    assert dump(sentences, handle) == 2
    assert handle.getvalue() == _DOC


_FIELD = st.text(
    alphabet=st.characters(
        blacklist_characters="\t\n\r|", blacklist_categories=("Cs",)
    ),
    min_size=1,
    max_size=6,
).filter(lambda s: s.strip() == s and s.strip() != "")


@st.composite
def _sentences(draw: st.DrawFn) -> ConlluSentence:
    """Draw a well-formed sentence with free-form forms, comments, and MISC."""
    count = draw(st.integers(min_value=1, max_value=4))
    comments = [
        f"# {draw(_FIELD)} = {draw(_FIELD)}" for _ in range(draw(st.integers(0, 2)))
    ]
    rows = []
    for word in range(1, count + 1):
        misc = "|".join(draw(st.lists(_FIELD, max_size=3))) or "_"
        head = draw(st.integers(min_value=0, max_value=count))
        rows.append(f"{word}\t{draw(_FIELD)}\t_\tX\t_\t_\t{head}\tdep\t_\t{misc}")
    return ConlluSentence.build(comments, rows)


@given(_sentences())
def test_round_trip_property(sentence: ConlluSentence) -> None:
    text = serialize([sentence])
    assert serialize(parse(text)) == text
    assert list(parse(text)) == [sentence]
