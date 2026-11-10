"""Unit tests for lairs.conllu.model."""

from __future__ import annotations

import didactic.api as dx
import pytest

from lairs.conllu.model import (
    Comment,
    ConlluRow,
    ConlluSentence,
    Dep,
    Feat,
    MiscItem,
    RowId,
    check_block,
    check_row,
    split_items,
)

_WORD = "2\tzu\tzu\tADP\tAPPR\tNumber[psor]=Sing|Case=Acc,Dat\t4\tcase\t4:case|4.1:dep\tBare|A=1|A=2|K=v=w"
_RANGE = "2-3\tzur\t_\t_\t_\tTypo=Yes\t_\t_\t_\tMwt=1"
_EMPTY = "4.1\tgeht\tgehen\tVERB\t_\tMood=Ind\t_\t_\t4:conj|0:root\t_"


def test_row_id_kinds_and_text() -> None:
    word, rng, empty, root = (RowId.parse(t) for t in ("7", "1-2", "3.1", "0"))
    assert (word.kind, rng.kind, empty.kind) == ("word", "range", "empty")
    assert word.is_word and rng.is_range and empty.is_empty
    assert root.is_word
    assert (rng.major, rng.end, empty.major, empty.minor) == (1, 2, 3, 1)
    assert [i.text for i in (word, rng, empty, root)] == ["7", "1-2", "3.1", "0"]
    assert RowId.parse("0.1") == RowId(major=0, minor=1)


def test_row_id_is_interned() -> None:
    assert RowId.parse("12") is RowId.parse("12")


@pytest.mark.parametrize("text", ["", "x", "01", "1-", "1.0", "-1", "1.1.1"])
def test_row_id_rejects_malformed(text: str) -> None:
    with pytest.raises(ValueError, match="malformed id"):
        RowId.parse(text)


def test_feat_layer_and_values() -> None:
    feat = Feat(name="Number[psor]", value="Sing,Plur")
    assert feat.feature == "Number"
    assert feat.layer == "psor"
    assert feat.values == ("Sing", "Plur")
    assert feat.text == "Number[psor]=Sing,Plur"
    plain = Feat(name="Case", value="Acc")
    assert (plain.feature, plain.layer) == ("Case", None)


def test_dep_and_misc_text() -> None:
    assert Dep(head=RowId.parse("4.1"), relation="obl:on").text == "4.1:obl:on"
    assert MiscItem(key="Bare").text == "Bare"
    assert MiscItem(key="K", value="v=w").text == "K=v=w"


def test_comment_key_and_value() -> None:
    keyed = Comment(text="  sent_id =  s1 ")
    assert (keyed.key, keyed.value, keyed.line) == ("sent_id", "s1", "#  sent_id =  s1 ")
    bare = Comment(text=" newdoc")
    assert (bare.key, bare.value) == ("newdoc", None)


def test_word_row_views() -> None:
    row = ConlluRow(line=_WORD)
    assert row.id == RowId(major=2)
    assert row.kind == "word"
    assert (row.form, row.lemma, row.upos, row.xpos) == ("zu", "zu", "ADP", "APPR")
    assert [f.text for f in row.feats] == ["Number[psor]=Sing", "Case=Acc,Dat"]
    assert (row.head, row.deprel) == (4, "case")
    assert [d.text for d in row.deps] == ["4:case", "4.1:dep"]
    assert row.deps[1].head.is_empty
    assert [m.text for m in row.misc] == ["Bare", "A=1", "A=2", "K=v=w"]
    assert row.misc[0].value is None
    assert row.misc_value("A") == "1"
    assert row.misc_value("Bare") is None
    assert row.misc_value("Missing") is None


def test_range_and_empty_rows() -> None:
    rng = ConlluRow(line=_RANGE)
    assert rng.kind == "range"
    assert (rng.lemma, rng.upos, rng.head, rng.deprel) == (None, None, None, None)
    assert rng.deps == ()
    empty = ConlluRow(line=_EMPTY)
    assert empty.kind == "empty"
    assert (empty.lemma, empty.head) == ("gehen", None)
    assert [d.head.text for d in empty.deps] == ["4", "0"]


def test_underscore_form_keeps_literal_lemma() -> None:
    underscore = ConlluRow(line="1\t_\t_\tPUNCT\t_\t_\t0\troot\t_\t_")
    assert (underscore.form, underscore.lemma) == ("_", "_")
    absent = ConlluRow(line="1\tx\t_\tX\t_\t_\t0\troot\t_\t_")
    assert absent.lemma is None


def test_build_round_trips_typed_values() -> None:
    row = ConlluRow(line=_WORD)
    rebuilt = ConlluRow.build(
        row.id,
        row.form,
        lemma=row.lemma,
        upos=row.upos,
        xpos=row.xpos,
        feats=row.feats,
        head=row.head,
        deprel=row.deprel,
        deps=row.deps,
        misc=row.misc,
    )
    assert rebuilt == row
    minimal = ConlluRow.build("1", "x")
    assert minimal.line == "1\tx\t_\t_\t_\t_\t_\t_\t_\t_"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("1\tx", "expected 10"),
        ("1\tx\t\t_\t_\t_\t_\t_\t_\t_", "column 3 is empty"),
        ("a\tx\t_\t_\t_\t_\t_\t_\t_\t_", "malformed id"),
        ("1\tx\t_\t_\t_\t_\tz\t_\t_\t_", "malformed HEAD"),
        ("1\tx\t_\t_\t_\tCase\t_\t_\t_\t_", "malformed FEATS"),
        ("1\tx\t_\t_\t_\t_\t_\t_\tnsubj\t_", "malformed DEPS"),
        ("1\tx\t_\t_\t_\t_\t_\t_\t1.x:dep\t_", "malformed DEPS"),
    ],
)
def test_check_row_rejects_malformed(line: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_row(line)


def test_row_constructor_validates() -> None:
    with pytest.raises(dx.ValidationError):
        ConlluRow(line="not a row")


def test_split_items() -> None:
    assert split_items("_") == ()
    assert split_items("a|b") == ("a", "b")


def test_sentence_views() -> None:
    block = "\n".join(["# sent_id = s1", "# text = zur", "# newdoc", _RANGE, _WORD])
    sentence = ConlluSentence(block=block)
    assert sentence.sent_id == "s1"
    assert sentence.text == "zur"
    assert sentence.comment("newdoc") is None
    assert [c.text for c in sentence.comments] == [" sent_id = s1", " text = zur", " newdoc"]
    assert [r.kind for r in sentence.rows] == ["range", "word"]
    assert [r.form for r in sentence.words] == ["zu"]
    assert sentence.row_lines == (_RANGE, _WORD)
    assert sentence.exact
    assert sentence.rows is sentence.rows


def test_sentence_without_comments_has_no_ids() -> None:
    sentence = ConlluSentence(block=_WORD)
    assert (sentence.sent_id, sentence.text, sentence.comments) == (None, None, ())


def test_sentence_build_and_lossy() -> None:
    sentence = ConlluSentence.build(
        [Comment(text=" sent_id = a"), "# text = zu"],
        [ConlluRow(line=_WORD), _EMPTY],
        lossy=["misc"],
    )
    assert sentence.block.splitlines()[0] == "# sent_id = a"
    assert sentence.lossy == ("misc",)
    assert not sentence.exact


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ("# only a comment", "no rows"),
        (f"{_WORD}\n# late", "comment after"),
        (f"{_WORD}\n\n{_WORD}", "blank line"),
        (f"# c\n{_WORD}\nbad", "line 3"),
    ],
)
def test_check_block_rejects_malformed(block: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_block(block)


def test_check_block_returns_first_row() -> None:
    assert check_block(f"# a\n# b\n{_WORD}") == 2
