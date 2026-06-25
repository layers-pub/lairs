"""Unit and integration tests for lairs.integrations.codecs.brat."""

from __future__ import annotations

import json

import didactic.api as dx
import pytest
from hypothesis import strategies as st

from lairs.integrations.codecs import CorpusFragment
from lairs.integrations.codecs.brat import (
    BratCodec,
    BratIso,
    _Attribute,
    _Entity,
    _parse_entity,
    _Relation,
    _Standoff,
    canonical_standoff,
    split_standoff,
)
from lairs.integrations.ports import Codec

# a small two-entity, one-relation, two-attribute fixture.
_TXT = "Barack Obama was born in Hawaii."
_ANN = (
    "T1\tPerson 0 12\tBarack Obama\n"
    "T2\tLocation 25 31\tHawaii\n"
    "R1\tBornIn Arg1:T1 Arg2:T2\n"
    "A1\tNegation T1\n"
    "A2\tConfidence T2 high"
)
_SRC = f"{_TXT}\n===ANN===\n{_ANN}"


def test_name() -> None:
    assert BratCodec.name == "brat"


def test_is_codec_protocol() -> None:
    assert isinstance(BratCodec(), Codec)


def test_decode_produces_expression_and_layers() -> None:
    fragment = BratCodec().decode(_SRC)
    locals_ = [record.local_id for record in fragment.records]
    assert locals_ == ["expression", "entities", "relations"]
    assert fragment.source == "brat"


def test_decode_omits_relation_layer_when_no_relations() -> None:
    fragment = BratCodec().decode("a b\n===ANN===\nT1\tX 0 1\ta")
    locals_ = [record.local_id for record in fragment.records]
    assert locals_ == ["expression", "entities"]


def test_decode_byte_offsets_are_preserved() -> None:
    fragment = BratCodec().decode(_SRC)
    entities = next(r for r in fragment.records if r.local_id == "entities")
    layer = json.loads(entities.value_json)
    first = layer["annotations"][0]
    assert first["anchor"]["textSpan"]["byteStart"] == 0
    assert first["anchor"]["textSpan"]["byteEnd"] == 12
    assert first["label"] == "Person"
    assert first["text"] == "Barack Obama"


def test_decode_attributes_become_features() -> None:
    fragment = BratCodec().decode(_SRC)
    entities = next(r for r in fragment.records if r.local_id == "entities")
    layer = json.loads(entities.value_json)
    hawaii = layer["annotations"][1]
    entries = hawaii["features"]["entries"]
    assert {"key": "Confidence", "value": "high"} in entries


def test_decode_binary_flag_attribute_uses_flag_sentinel() -> None:
    # a brat binary flag (no value) is carried as an empty feature value so it
    # cannot collide with a genuine value such as the literal "true".
    fragment = BratCodec().decode(_SRC)
    entities = next(r for r in fragment.records if r.local_id == "entities")
    layer = json.loads(entities.value_json)
    obama = layer["annotations"][0]
    entries = obama["features"]["entries"]
    assert {"key": "Negation", "value": ""} in entries


def test_decode_relation_arguments() -> None:
    fragment = BratCodec().decode(_SRC)
    relations = next(r for r in fragment.records if r.local_id == "relations")
    layer = json.loads(relations.value_json)
    arc = layer["annotations"][0]
    assert arc["label"] == "BornIn"
    targets = [arg["target"]["localId"]["value"] for arg in arc["arguments"]]
    assert targets == ["T1", "T2"]


def test_decode_accepts_bytes() -> None:
    fragment = BratCodec().decode(_SRC.encode("utf-8"))
    assert fragment.records[0].local_id == "expression"


def test_encode_returns_str() -> None:
    # the Codec port permits bytes or str; the brat codec always emits str.
    fragment = BratCodec().decode(_SRC)
    assert isinstance(BratCodec().encode(fragment.records), str)


def test_decode_discontinuous_entity_collapses_to_enclosing_span() -> None:
    # a fragmented entity (Type 0 5;8 12) is collapsed to the enclosing span.
    fragment = BratCodec().decode(
        "abcdefghijklm\n===ANN===\nT1\tFrag 0 5;8 12\tabcde lm"
    )
    entities = next(r for r in fragment.records if r.local_id == "entities")
    layer = json.loads(entities.value_json)
    span = layer["annotations"][0]["anchor"]["textSpan"]
    assert span["byteStart"] == 0
    assert span["byteEnd"] == 12


def test_parse_entity_handles_single_and_fragmented_offsets() -> None:
    single = _parse_entity("T1\tType 3 7\tword")
    assert single is not None
    assert (single.byte_start, single.byte_end) == (3, 7)
    fragmented = _parse_entity("T2\tType 3 7;10 14\tword frag")
    assert fragmented is not None
    assert (fragmented.byte_start, fragmented.byte_end) == (3, 14)


def test_parse_entity_rejects_malformed_offsets() -> None:
    assert _parse_entity("T1\tType notanumber 7\tword") is None
    assert _parse_entity("T1\tType 3\tword") is None


def test_decode_skips_unsupported_line_kinds() -> None:
    # event, normalisation, equivalence, and note lines are silently dropped;
    # the supported T line still decodes.
    src = (
        "x\n===ANN===\n"
        "T1\tType 0 1\tx\n"
        "E1\tType:T1\n"
        "N1\tReference T1 Wikipedia:123\n"
        "*\tEquiv T1 T1\n"
        "#1\tAnnotatorNotes T1\ta note"
    )
    fragment = BratCodec().decode(src)
    entities = next(r for r in fragment.records if r.local_id == "entities")
    layer = json.loads(entities.value_json)
    assert len(layer["annotations"]) == 1
    assert "relations" not in [r.local_id for r in fragment.records]


def test_attribute_value_true_round_trips_distinct_from_flag() -> None:
    # a binary flag and an attribute whose value is literally "true" must not
    # collapse onto each other through encode/decode.
    src = "word\n===ANN===\nT1\tType 0 4\tword\nA1\tFlag T1\nA2\tStatus T1 true"
    codec = BratCodec()
    once = codec.decode(src)
    twice = codec.decode(codec.encode(once.records))
    assert once == twice
    entities = next(r for r in twice.records if r.local_id == "entities")
    layer = json.loads(entities.value_json)
    entries = layer["annotations"][0]["features"]["entries"]
    by_key = {entry["key"]: entry["value"] for entry in entries}
    assert by_key["Flag"] == ""
    assert by_key["Status"] == "true"


def test_split_standoff_recovers_txt_and_ann_halves() -> None:
    codec = BratCodec()
    encoded = codec.encode(codec.decode(_SRC).records)
    txt, ann = split_standoff(encoded)
    assert txt == _TXT
    assert ann == _ANN


def test_split_standoff_accepts_bytes_and_bare_ann() -> None:
    txt, ann = split_standoff(b"doc\n===ANN===\nT1\tType 0 1\td")
    assert txt == "doc"
    assert ann == "T1\tType 0 1\td"
    bare_txt, bare_ann = split_standoff("T1\tType 0 1\td")
    assert bare_txt == ""
    assert bare_ann == "T1\tType 0 1\td"


def test_decode_into_extends_existing_fragment() -> None:
    codec = BratCodec()
    first = codec.decode("a\n===ANN===\nT1\tX 0 1\ta")
    second = codec.decode("b\n===ANN===\nT1\tY 0 1\tb", into=first)
    assert len(second.records) == len(first.records) + 2


def test_encode_round_trips_source_text() -> None:
    codec = BratCodec()
    fragment = codec.decode(_SRC)
    assert codec.encode(fragment.records) == _SRC


def test_round_trip_decode_encode_decode_is_stable() -> None:
    codec = BratCodec()
    once = codec.decode(_SRC)
    twice = codec.decode(codec.encode(once.records))
    assert once == twice


def test_iso_backward_forward_on_canonical_standoff() -> None:
    standoff = canonical_standoff(
        _Standoff(
            text="abc def",
            entities=(
                _Entity(tag="T1", type_name="X", byte_start=0, byte_end=3, text="abc"),
                _Entity(tag="T2", type_name="Y", byte_start=4, byte_end=7, text="def"),
            ),
            relations=(_Relation(tag="R1", type_name="Rel", arg1="T1", arg2="T2"),),
            attributes=(
                _Attribute(tag="A1", type_name="Neg", target="T1", value=None),
                _Attribute(tag="A2", type_name="Conf", target="T2", value="high"),
            ),
        )
    )
    iso = BratIso()
    assert iso.backward(iso.forward(standoff)) == standoff


def test_canonical_standoff_is_idempotent() -> None:
    standoff = _Standoff(
        text="x y",
        entities=(
            _Entity(tag="E_a", type_name="X", byte_start=0, byte_end=1, text="x"),
        ),
        attributes=(_Attribute(tag="A_z", type_name="F", target="E_a", value="v"),),
    )
    once = canonical_standoff(standoff)
    assert canonical_standoff(once) == once


@st.composite
def _standoffs(draw: st.DrawFn) -> _Standoff:
    """Draw a canonical, round-trippable brat standoff."""
    labels = st.text(alphabet="ABCDEFvalue", min_size=1, max_size=6)
    # exclude the exact string "null": didactic serialises an optional str|None
    # field holding "null" as JSON null, so it cannot round-trip. tracked as
    # didactic issue #57; remove this filter once that lands.
    texts = st.text(min_size=0, max_size=20).filter(lambda value: value != "null")
    count = draw(st.integers(min_value=0, max_value=4))
    entities = tuple(
        _Entity(
            tag=f"raw{i}",
            type_name=draw(labels),
            byte_start=i,
            byte_end=i + 1,
            text=draw(texts),
        )
        for i in range(count)
    )
    relations: tuple[_Relation, ...] = ()
    pair = 2
    if count >= pair:
        relations = (
            _Relation(
                tag="raw-r",
                type_name=draw(labels),
                arg1=entities[0].tag,
                arg2=entities[1].tag,
            ),
        )
    attributes = tuple(
        _Attribute(
            tag=f"raw-a{i}",
            type_name=draw(labels),
            target=entities[i].tag,
            value=draw(st.one_of(st.none(), labels)),
        )
        for i in range(count)
    )
    return canonical_standoff(
        _Standoff(
            text=draw(texts),
            entities=entities,
            relations=relations,
            attributes=attributes,
        )
    )


def test_iso_law_property() -> None:
    dx.testing.verify_iso(_RoundTripIso(), _standoffs(), max_examples=50)


class _RoundTripIso(dx.Iso[_Standoff, _Standoff]):
    """Compose the brat Iso with its inverse for ``verify_iso``."""

    def forward(self, a: _Standoff, /) -> _Standoff:
        iso = BratIso()
        return iso.backward(iso.forward(a))

    def backward(self, b: _Standoff, /) -> _Standoff:
        return b


@pytest.mark.integration
def test_roundtrip_live() -> None:
    codec = BratCodec()
    fragment = codec.decode(_SRC)
    assert isinstance(fragment, CorpusFragment)
    assert codec.encode(fragment.records) == _SRC
