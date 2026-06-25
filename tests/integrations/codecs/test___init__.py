"""Unit tests for lairs.integrations.codecs package surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from lairs.integrations import codecs
from lairs.integrations.codecs import CorpusFragment, FragmentRecord
from lairs.integrations.ports import Codec
from lairs.integrations.registry import available, get_codec


def test_exports() -> None:
    assert set(codecs.__all__) == {
        "BratCodec",
        "BratIso",
        "ConlluCodec",
        "ConlluIso",
        "CorpusFragment",
        "FragmentRecord",
    }


def test_reference_codecs_reachable_from_package() -> None:
    # every public codec and Iso is importable from the package surface, not
    # only from the private-looking submodules.
    for name in ("BratCodec", "BratIso", "ConlluCodec", "ConlluIso"):
        assert hasattr(codecs, name)


def test_importing_package_does_not_import_conllu(
    assert_lazy_import: Callable[..., None],
) -> None:
    # re-exporting the codec classes must not pull the conllu codec's optional
    # third-party extra into a core install.
    assert_lazy_import("lairs.integrations.codecs", "conllu")


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
