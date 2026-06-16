"""Unit tests for lairs.integrations.codecs package surface."""

from __future__ import annotations

from lairs.integrations import codecs
from lairs.integrations.codecs import CorpusFragment, FragmentRecord
from lairs.integrations.ports import Codec
from lairs.integrations.registry import available, get_codec


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


def test_reference_codecs_are_discoverable() -> None:
    names = available("codecs")
    assert {"conllu", "brat"} <= set(names)


def test_discovered_codecs_satisfy_the_port() -> None:
    for name in ("conllu", "brat"):
        codec = get_codec(name)()
        assert isinstance(codec, Codec)
        assert codec.name == name
