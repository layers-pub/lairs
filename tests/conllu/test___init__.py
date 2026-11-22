"""Unit tests for the lairs.conllu package surface."""

from __future__ import annotations

import lairs
from lairs import conllu


def test_exports_are_reachable() -> None:
    for name in conllu.__all__:
        assert hasattr(conllu, name)


def test_reachable_from_the_top_level_package() -> None:
    assert lairs.conllu is conllu
    assert lairs.conllu.sentences is conllu.reader.sentences


def test_issue_usage_shape() -> None:
    text = "# sent_id = s\n# text = a\n1\ta\ta\tX\t_\t_\t0\troot\t0:root\t_\n\n"
    mapping = {r.uri: r.value() for r in conllu.Projector().project(conllu.parse(text))}
    for sentence in lairs.conllu.sentences(mapping):
        assert (sentence.sent_id, [c.key for c in sentence.comments]) == (
            "s",
            ["sent_id", "text"],
        )
        for row in sentence.rows:
            values = (row.id.text, row.form, row.lemma, row.upos, row.xpos)
            assert values == ("1", "a", "a", "X", None)
            assert (row.feats, row.head, row.deprel, row.misc) == ((), 0, "root", ())
            assert [dep.text for dep in row.deps] == ["0:root"]
