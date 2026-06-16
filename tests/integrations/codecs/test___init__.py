"""Unit tests for lairs.integrations.codecs package surface."""

from __future__ import annotations

from lairs.integrations import codecs
from lairs.integrations.codecs import CorpusFragment, FragmentRecord


def test_exports() -> None:
    assert set(codecs.__all__) == {"CorpusFragment", "FragmentRecord"}


def test_fragment_record_construction() -> None:
    rec = FragmentRecord(local_id="a", nsid="pub.layers.expression", value_json="{}")
    assert rec.local_id == "a"


def test_corpus_fragment_roundtrip() -> None:
    frag = CorpusFragment(
        records=(
            FragmentRecord(local_id="a", nsid="pub.layers.expression", value_json="{}"),
        ),
        source="conllu",
    )
    back = CorpusFragment.model_validate_json(frag.model_dump_json())
    assert back == frag
