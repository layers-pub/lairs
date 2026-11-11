"""Unit tests for lairs.conllu.projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lairs.conllu.projection import (
    ALIGNMENT_NSID,
    ANNOTATION_NSID,
    EXPRESSION_NSID,
    MEMBERSHIP_NSID,
    SEGMENTATION_NSID,
    FeatResolution,
    LocalNaming,
    NoOntology,
    OntologyResolver,
    ProjectedRecord,
    Projector,
    RecordNaming,
    sentence_from_json,
    sentence_from_records,
)
from lairs.conllu.text import parse, serialize
from lairs.records._generated.alignment import Alignment
from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.defs import Feature
from lairs.records._generated.expression import Expression
from lairs.records._generated.segmentation import Segmentation

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs._types import JsonValue
    from lairs.conllu.model import ConlluSentence
    from lairs.conllu.projection import JsonObject

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
    "# sent_id = s3\n"
    "# text = x y\n"
    "1\tx\tx\tX\t_\t_\t_\t_\t_\tNote=1\n"
    "2\ty\ty\tX\t_\t_\t_\t_\t_\t_\n"
    "\n"
)


def _records(
    text: str = _DOC,
    projector: Projector | None = None,
) -> list[ProjectedRecord]:
    """Project every sentence of ``text``."""
    return list((projector or Projector()).project(parse(text)))


def _rebuild(records: Sequence[ProjectedRecord]) -> list[ConlluSentence]:
    """Rebuild each sentence of a projection from its JSON records."""
    expressions = [r for r in records if r.role == "expr"]
    out = []
    for expression in expressions:
        mine = [
            r
            for r in records
            if json.loads(r.value_json).get("expression") == expression.uri
        ]
        out.append(
            sentence_from_json(
                expression.value(),
                [r.value() for r in mine if r.nsid == SEGMENTATION_NSID],
                [r.value() for r in mine if r.nsid == ANNOTATION_NSID],
                [r.value() for r in mine if r.nsid == ALIGNMENT_NSID],
            )
        )
    return out


def _by_role(
    records: Sequence[ProjectedRecord], ordinal: int = 0
) -> dict[str, JsonObject]:
    """Return one sentence's records keyed by role."""
    marker = f"-{ordinal}-"
    return {r.role: r.value() for r in records if marker in r.local_id}


def _layer_annotations(layer: JsonObject) -> list[JsonObject]:
    """Return a layer's annotations as JSON objects."""
    annotations = layer["annotations"]
    assert isinstance(annotations, list)
    return [a for a in annotations if isinstance(a, dict)]


def _features(value: JsonValue) -> list[tuple[str, str]]:
    """Return the entries of a feature-map JSON value."""
    assert isinstance(value, dict)
    entries = value["entries"]
    assert isinstance(entries, list)
    pairs = []
    for entry in entries:
        assert isinstance(entry, dict)
        key, val = entry["key"], entry["value"]
        assert isinstance(key, str)
        assert isinstance(val, str)
        pairs.append((key, val))
    return pairs


# a row the reader contract cannot represent: a HEAD with no DEPREL, and a
# FEATS key that recurs after another key (the contract groups values by key).
_ODD = (
    "# sent_id = odd\n"
    "1\ta\t_\tX\t_\tA=1|B=2|A=3\t0\t_\t_\t_\n"
    "2\tb\t_\tX\t_\t_\t1\tdep\t_\t_\n\n"
)


def _legacy(records: Sequence[ProjectedRecord]) -> list[ProjectedRecord]:
    """Reduce a projection to the shape the importer published before the contract.

    That shape had no verbatim comment block, no MISC layers, no token-tag
    layers over empty nodes, no verbatim range-line columns, and FEATS labels
    without their layer.
    """
    out: list[ProjectedRecord] = []
    for record in records:
        tag_over_empties = record.role.endswith("-enhanced") and record.role != (
            "seg-enhanced"
        )
        if record.role == "misc" or tag_over_empties:
            continue
        value = record.value()
        if record.role == "expr":
            kept: list[JsonValue] = [
                {"key": key, "value": val}
                for key, val in _features(value["features"])
                if not key.startswith("ud_comment")
            ]
            value["features"] = {"entries": kept}
        elif record.role == "morph":
            for annotation in _layer_annotations(value):
                label = annotation["label"]
                assert isinstance(label, str)
                name, _, val = label.partition("=")
                annotation["label"] = f"{name.partition('[')[0]}={val}"
        elif record.role == "align":
            links = value["links"]
            assert isinstance(links, list)
            for link in links:
                assert isinstance(link, dict)
                if "features" in link:
                    link["features"] = {
                        "entries": [
                            {"key": key, "value": val}
                            for key, val in _features(link["features"])
                            if key not in {"ud_feats", "ud_misc"}
                        ]
                    }
        out.append(record.with_(value_json=json.dumps(value, ensure_ascii=False)))
    return out


def test_every_record_validates_into_its_model() -> None:
    for record in _records():
        model = record.to_model()
        assert type(model).__name__ in {
            "Expression",
            "Segmentation",
            "Alignment",
            "AnnotationLayer",
        }


def test_round_trip_is_exact() -> None:
    rebuilt = _rebuild(_records())
    assert serialize(rebuilt) == _DOC
    assert all(sentence.exact for sentence in rebuilt)


def test_published_shape_of_a_sentence() -> None:
    roles = _by_role(_records())
    assert set(roles) == {
        "expr", "seg", "align", "upos", "xpos", "lemma", "morph", "misc", "deps",
        "seg-enhanced", "edeps", "upos-enhanced", "xpos-enhanced",
        "lemma-enhanced", "morph-enhanced", "misc-enhanced",
    }  # fmt: skip
    expression = roles["expr"]
    assert (expression["id"], expression["kind"]) == ("s1", "sentence")
    assert expression["text"] == "Über zur Schule…"
    # the verbatim comment block first, then the queryable key = value view.
    assert _features(expression["features"]) == [
        ("ud_comment_lines", "6"),
        ("ud_comment", "# newdoc id = doc1"),
        ("ud_comment", "# newpar id = par1"),
        ("ud_comment", "# sent_id = s1"),
        ("ud_comment", "# text = Über zur Schule…"),
        ("ud_comment", "#  odd spacing =  kept  "),
        ("ud_comment", "# free text without an equals sign"),
        ("odd spacing", "kept"),
    ]
    tokenizations = roles["seg"]["tokenizations"]
    assert isinstance(tokenizations, list)
    surface, words = (t for t in tokenizations if isinstance(t, dict))
    assert surface["uuid"] == {"value": "conllu/0/surface"}
    assert words["uuid"] == {"value": "conllu/0/words"}
    surface_tokens = surface["tokens"]
    assert isinstance(surface_tokens, list)
    assert [t["text"] for t in surface_tokens if isinstance(t, dict)] == [
        "Über",
        "zur",
        "Schule",
        "…",
    ]
    word_tokens = words["tokens"]
    assert isinstance(word_tokens, list)
    spans = [t["textSpan"] for t in word_tokens if isinstance(t, dict)]
    # non-ascii forms get utf-8 byte offsets; the words of zur share its span.
    assert spans[0] == {"byteStart": 0, "byteEnd": 5}
    assert spans[1] == spans[2] == {"byteStart": 6, "byteEnd": 9}
    assert spans[4] == {"byteStart": 16, "byteEnd": 19}


def test_published_layers_follow_the_importer_conventions() -> None:
    roles = _by_role(_records())
    morph = [a["label"] for a in _layer_annotations(roles["morph"])]
    # the label keeps the layered key; a multi-valued feature is one per value.
    assert morph == ["Number[psor]=Sing", "Case=Acc", "Case=Dat", "Gender=Fem"]
    deps = _layer_annotations(roles["deps"])
    assert [a["headIndex"] for a in deps] == [3, 3, 3, -1, 3]
    assert _features(deps[0]["features"]) == [
        ("ud_relation", "case"), ("A", "3"), ("Bare", ""), ("Z", "1"),
    ]  # fmt: skip
    edeps = _layer_annotations(roles["edeps"])
    empty_arcs = [
        a for a in edeps if ("ud_empty_node", "4.1") in _features(a["features"])
    ]
    assert [a["headIndex"] for a in empty_arcs] == [3, -1]
    assert roles["edeps"]["parentLayerRef"] == (
        "at://local/pub.layers.annotation.annotationLayer/conllu-0-deps"
    )
    links = roles["align"]["links"]
    assert isinstance(links, list)
    labels = [link["label"] for link in links if isinstance(link, dict)]
    assert labels == ["one-to-one", "multiword-token", "one-to-one", "one-to-one"]
    mwt = links[1]
    assert isinstance(mwt, dict)
    # the queryable view, then the range line's verbatim FEATS and MISC.
    assert _features(mwt["features"]) == [
        ("Mwt", "1"), ("feats:Typo", "Yes"), ("ud_feats", "Typo=Yes"),
        ("ud_misc", "Mwt=1"),
    ]  # fmt: skip
    assert all(
        layer.get("formalism") == "universal-dependencies"
        for layer in (roles["upos"], roles["deps"], roles["edeps"], roles["morph"])
    )


def test_misc_and_empty_node_layers_follow_the_reader_contract() -> None:
    roles = _by_role(_records())
    misc = roles["misc"]
    assert (misc["subkind"], misc["labelSet"]) == ("misc", "ud-misc")
    # one annotation per word that has a MISC column, holding it verbatim.
    assert [(a["tokenIndex"], a["value"]) for a in _layer_annotations(misc)] == [
        (0, "Z=1|Bare|A=2|A=3"),
        (3, "SpaceAfter=No"),
    ]
    for role, field, expected in (
        ("upos-enhanced", "label", "VERB"),
        ("xpos-enhanced", "label", "VVFIN"),
        ("lemma-enhanced", "value", "gehen"),
        ("morph-enhanced", "label", "Mood=Ind"),
        ("misc-enhanced", "value", "Gloss=go"),
    ):
        layer = roles[role]
        assert layer["tokenizationId"] == {"value": "conllu/0/enhanced"}
        words_role = role.removesuffix("-enhanced")
        assert layer["parentLayerRef"] == (
            f"at://local/pub.layers.annotation.annotationLayer/conllu-0-{words_role}"
        )
        (annotation,) = _layer_annotations(layer)
        # the empty node is token 5 of the enhanced tokenization: five words first.
        assert annotation["tokenIndex"] == 5
        assert annotation[field] == expected
        assert ("ud_empty_node", "4.1") in _features(annotation["features"])


def test_empty_node_without_misc_still_names_itself() -> None:
    text = "1\ta\t_\tX\t_\t_\t0\troot\t_\t_\n1.1\t_\t_\t_\t_\t_\t_\t_\t_\t_\n\n"
    records = _records(text)
    roles = _by_role(records)
    assert "edeps" not in roles
    (annotation,) = _layer_annotations(roles["misc-enhanced"])
    assert annotation["value"] == "_"
    assert _features(annotation["features"]) == [("ud_empty_node", "1.1")]
    assert serialize(_rebuild(records)) == text


def test_valid_ud_needs_no_residual_carriers() -> None:
    records = _records()
    assert all(r.role != "conllu" for r in records)
    assert all("conllu:" not in r.value_json for r in records)


def test_residual_carriers_cover_what_the_contract_cannot_hold() -> None:
    records = _records(_ODD)
    roles = _by_role(records)
    carriers = [
        p for p in _features(roles["expr"]["features"]) if p[0].startswith("conllu:")
    ]
    assert carriers == [("conllu:scheme", "1"), ("conllu:rows", "1")]
    rows = {
        a["label"]: _features(a["features"])
        for a in _layer_annotations(roles["conllu"])
    }
    assert rows == {"1": [("conllu:feats", "A=1|B=2|A=3"), ("conllu:head", "0")]}
    rebuilt = _rebuild(records)
    assert serialize(rebuilt) == _ODD
    assert rebuilt[0].exact


def test_without_carriers_the_shape_is_published_only() -> None:
    records = _records(projector=Projector(carriers=False))
    assert all(r.role != "conllu" for r in records)
    for record in records:
        if record.role == "expr":
            assert "conllu:" not in record.value_json


def test_lossy_reconstruction_flags_what_it_could_not_restore() -> None:
    rebuilt = _rebuild(_legacy(_records()))
    first = rebuilt[0]
    assert set(first.lossy) == {
        "comments",
        "misc",
        "feats",
        "empty_nodes",
        "multiword_tokens",
    }
    rows = {row.id.text: row for row in first.rows}
    # sorted pairs, a bare item, and SpaceAfter=No inferred from adjacent spans.
    assert rows["1"].columns[9] == "A=3|Bare|Z=1"
    assert rows["4"].columns[9] == "SpaceAfter=No"
    assert rows["2"].columns[5] == "Number=Sing|Case=Acc,Dat"
    assert rows["2-3"].columns[5] == "Typo=Yes"
    assert rows["2-3"].columns[9] == "Mwt=1"
    assert rows["4.1"].line == "4.1\tgeht\t_\t_\t_\t_\t_\t_\t4:conj|0:root\t_"
    assert first.comment_lines[:2] == ("# sent_id = s1", "# odd spacing = kept")
    third = rebuilt[2]
    # a word with no head has nowhere to publish its MISC.
    assert third.rows[0].columns[9] == "_"


def test_non_canonical_order_is_carried() -> None:
    text = (
        "1\tb\t_\tX\t_\t_\t0\troot\t_\t_\n"
        "1.1\te\t_\t_\t_\t_\t_\t_\t1:dep\t_\n"
        "2-3\tcd\t_\t_\t_\t_\t_\t_\t_\t_\n"
        "2\tc\t_\tX\t_\t_\t1\tdep\t_\t_\n"
        "3\td\t_\tX\t_\t_\t1\tdep\t_\t_\n"
        "\n"
    )
    reordered = text.replace(
        "1.1\te\t_\t_\t_\t_\t_\t_\t1:dep\t_\n2-3\tcd\t_\t_\t_\t_\t_\t_\t_\t_\n",
        "2-3\tcd\t_\t_\t_\t_\t_\t_\t_\t_\n1.1\te\t_\t_\t_\t_\t_\t_\t1:dep\t_\n",
    )
    for source in (text, reordered):
        records = _records(source)
        order = "conllu:order" in records[0].value_json
        assert order is (source == reordered)
        assert serialize(_rebuild(records)) == source


def test_long_values_are_split_and_rejoined() -> None:
    long_misc = "Note=" + "é" * 5000
    long_feats = "Long=" + "ü" * 3000
    text = (
        f"# comment {'ü' * 4100}\n"
        f"1-2\txy\t_\t_\t_\t{long_feats}\t_\t_\t_\t{long_misc}\n"
        f"1\tx\t_\tX\t_\t_\t0\troot\t_\t{long_misc}\n"
        "2\ty\t_\tX\t_\t_\t1\tdep\t_\t_\n\n"
    )
    records = _records(text)
    joined = "".join(r.value_json for r in records)
    for key in ("ud_comment+", "ud_misc+", "ud_feats+"):
        assert f'"{key}"' in joined

    def strings(value: JsonValue) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [s for item in value for s in strings(item)]
        if isinstance(value, dict):
            return [s for item in value.values() for s in strings(item)]
        return []

    for record in records:
        # every feature value, label, and annotation value fits the lexicon's
        # 4096-byte limit, the queryable views included.
        value = record.value()
        checked = value.get("features") if record.role == "expr" else value
        assert all(len(s.encode("utf-8")) <= 4096 for s in strings(checked))
    assert serialize(_rebuild(records)) == text


def test_long_residual_carrier_values_are_split_and_rejoined() -> None:
    # a FEATS key that recurs out of order is regrouped by the contract, so
    # the whole column travels in a residual carrier.
    text = f"1\tx\t_\tX\t_\tA=1|B={'é' * 5000}|A=3\t0\troot\t_\t_\n\n"
    records = _records(text)
    assert '"conllu:more"' in "".join(r.value_json for r in records)
    assert serialize(_rebuild(records)) == text


def test_sentence_without_text_or_id() -> None:
    text = (
        "1\ta\t_\tX\t_\t_\t0\troot\t_\tSpaceAfter=No\n"
        "2\tb\t_\tX\t_\t_\t1\tdep\t_\t_\n\n"
    )
    records = _records(text)
    expression = records[0].value()
    assert expression["id"] == "s0"
    assert expression["text"] == "ab"
    assert serialize(_rebuild(records)) == text


def test_membership_and_stamps() -> None:
    stamp = datetime(2024, 5, 1, tzinfo=UTC)
    projector = Projector(
        corpus_ref="at://did:plc:c/pub.layers.corpus.corpus/ud",
        split="dev",
        created_at=stamp,
        languages=["de"],
        source_method="manual",
    )
    roles = _by_role(_records(projector=projector))
    membership = roles["mem"]
    assert membership["split"] == "dev"
    assert membership["ordinal"] == 0
    assert membership["corpusRef"] == "at://did:plc:c/pub.layers.corpus.corpus/ud"
    assert roles["expr"]["languages"] == ["de"]
    assert roles["upos"]["sourceMethod"] == "manual"
    assert roles["expr"]["createdAt"] == stamp.isoformat()
    record = next(r for r in _records(projector=projector) if r.nsid == MEMBERSHIP_NSID)
    assert record.to_model().ordinal == 0


def test_structure_expressions_are_emitted_once() -> None:
    records = _records()
    kinds = [r.role for r in records if r.nsid == EXPRESSION_NSID and r.role != "expr"]
    assert kinds == ["document", "paragraph", "paragraph"]
    second = _by_role(records, 1)["expr"]
    paragraph = next(
        r for r in records if r.role == "paragraph" and "newpar:" in r.value_json
    )
    assert second["parentRef"] == paragraph.uri
    third = _by_role(records, 2)["expr"]
    assert third["parentRef"] == paragraph.uri


class _ImporterNaming:
    """The Layers UD importer's naming scheme."""

    def __init__(self, stem: str) -> None:
        self.stem = stem

    def local_id(self, role: str, sentence_id: str, ordinal: int) -> str:  # noqa: ARG002
        return f"{self.stem}/{sentence_id}/{role}"

    def uuid(self, role: str, sentence_id: str, ordinal: int) -> str:  # noqa: ARG002
        return f"{self.stem}/{sentence_id}/{role}"

    def unit_local_id(self, kind: str, unit_id: str, index: int) -> str:  # noqa: ARG002
        prefix = "doc" if kind == "document" else "par"
        return f"{self.stem}/{prefix}/{unit_id}"

    def reference(self, nsid: str, local_id: str) -> str:  # noqa: ARG002
        return f"at://local/{local_id}"


class _Ontology:
    """A resolver that references every label and normalises one value."""

    def ontology(self, kind: str) -> str | None:
        return f"at://ont/{kind}"

    def pos_type(self, upos: str) -> str | None:
        return f"at://ont/pos/{upos.lower()}"

    def deprel_type(self, deprel: str) -> str | None:
        return f"at://ont/deprel/{deprel.split(':', maxsplit=1)[0]}"

    def feat(self, feature: str, value: str) -> FeatResolution:
        if (feature, value) == ("Gender", "Fem"):
            return FeatResolution(
                feature="Gender",
                value="Fem2",
                type_ref="at://ont/feats/Gender-Fem2",
                extra=(
                    Feature(key="ud_feats_original", value="Gender=Fem"),
                    Feature(key="ud_feats_normalized", value="true"),
                ),
            )
        return FeatResolution(feature=feature, value=value, type_ref="at://ont/x")


def test_seams_are_injectable() -> None:
    # the importer names records by sent_id and falls back to s<ordinal>, so
    # every sentence here gets an id to keep the names distinct.
    doc = _DOC.replace("# newpar\n", "# newpar\n# sent_id = s2\n")
    naming = _ImporterNaming("ewt.eng.ud")
    assert isinstance(naming, RecordNaming)
    assert isinstance(_Ontology(), OntologyResolver)
    projector = Projector(
        naming=naming, ontology=_Ontology(), tool="layers-repo ud importer"
    )
    records = _records(doc, projector=projector)
    expression = next(r for r in records if r.role == "expr")
    assert expression.local_id == "ewt.eng.ud/s1/expr"
    segmentation = next(r for r in records if r.role == "seg")
    assert segmentation.value()["expression"] == "at://local/ewt.eng.ud/s1/expr"
    assert "ewt.eng.ud/s1/surface" in segmentation.value_json
    upos = next(r for r in records if r.role == "upos").value()
    assert upos["ontologyRef"] == "at://ont/pos"
    assert _layer_annotations(upos)[0]["ontologyTypeRef"] == "at://ont/pos/adp"
    morph = next(r for r in records if r.role == "morph").value()
    labels = [a["label"] for a in _layer_annotations(morph)]
    assert "Gender=Fem2" in labels
    # the published original undoes the normalisation, so no carrier is needed.
    rebuilt = _rebuild(records)
    assert serialize(rebuilt) == doc
    lossy_projector = Projector(naming=naming, ontology=_Ontology(), carriers=False)
    lossy = _rebuild(list(lossy_projector.project(parse(doc))))
    assert "Gender=Fem" in lossy[0].rows[4].line
    assert (
        next(r for r in records if r.role == "document").local_id
        == "ewt.eng.ud/doc/doc1"
    )


def test_defaults() -> None:
    naming = LocalNaming("x")
    assert naming.local_id("expr", "s", 3) == "x-3-expr"
    assert naming.uuid("words", "s", 3) == "x/3/words"
    assert naming.unit_local_id("document", "d", 0) == "x-document-0"
    assert naming.reference(EXPRESSION_NSID, "k") == f"at://local/{EXPRESSION_NSID}/k"
    none = NoOntology()
    assert (none.ontology("pos"), none.pos_type("X"), none.deprel_type("dep")) == (
        None,
    ) * 3
    assert none.feat("Case", "Acc") == FeatResolution(feature="Case", value="Acc")


def test_wire_json_with_nulls_and_types_reads_the_same() -> None:
    records = _records()

    def wire(record: ProjectedRecord) -> JsonObject:
        value = record.to_model().model_dump_json()
        loaded = json.loads(value)
        assert isinstance(loaded, dict)
        loaded["$type"] = record.nsid
        return loaded

    expression = next(r for r in records if r.role == "expr")
    mine = [
        r
        for r in records
        if r.role not in {"expr", "document", "paragraph"} and "-0-" in r.local_id
    ]
    rebuilt = sentence_from_json(
        wire(expression),
        [wire(r) for r in mine if r.nsid == SEGMENTATION_NSID],
        [wire(r) for r in mine if r.nsid == ANNOTATION_NSID],
        [wire(r) for r in mine if r.nsid == ALIGNMENT_NSID],
    )
    assert serialize([rebuilt]) == serialize([next(iter(parse(_DOC)))])


def test_sentence_from_records_accepts_models() -> None:
    records = [r for r in _records() if "-0-" in r.local_id]
    models = {r.role: r.to_model() for r in records}
    expression = models["expr"]
    assert isinstance(expression, Expression)
    segmentations = [m for m in models.values() if isinstance(m, Segmentation)]
    layers = [m for m in models.values() if isinstance(m, AnnotationLayer)]
    alignments = [m for m in models.values() if isinstance(m, Alignment)]
    rebuilt = sentence_from_records(expression, segmentations, layers, alignments)
    assert rebuilt.exact
    assert rebuilt.sent_id == "s1"


def test_missing_carrier_layer_is_flagged() -> None:
    records = [r for r in _records(_ODD) if r.role != "conllu"]
    rebuilt = _rebuild(records)[0]
    assert "carriers" in rebuilt.lossy


def test_comment_count_mismatch_is_flagged() -> None:
    records = _records()
    expression = records[2].value()
    assert expression["id"] == "s1"
    entries = _features(expression["features"])
    kept: list[JsonValue] = [
        {"key": k, "value": v} for k, v in entries if "free text" not in v
    ]
    expression["features"] = {"entries": kept}
    records[2] = records[2].with_(value_json=json.dumps(expression))
    assert _rebuild(records)[0].lossy == ("comments",)


def test_lossy_comments_restore_structure_markers() -> None:
    records = _legacy(_records())
    expression = next(r for r in records if r.role == "expr").value()
    units = [r.value() for r in records if r.role in {"document", "paragraph"}][:2]
    rebuilt = sentence_from_json(
        expression,
        [r.value() for r in records if r.role == "seg" and "-0-" in r.local_id],
        opened=units,
    )
    assert rebuilt.comment_lines[:2] == ("# newdoc id = doc1", "# newpar id = par1")
    bare = sentence_from_json(
        expression,
        [r.value() for r in records if r.role == "seg" and "-0-" in r.local_id],
        opened=[{"kind": "document", "id": "newdoc:s1"}],
    )
    assert bare.comment_lines[0] == "# newdoc"


def test_records_without_rows_raise() -> None:
    with pytest.raises(ValueError, match="no token rows"):
        sentence_from_json({"id": "x", "kind": "sentence"})


def test_projected_record_helpers() -> None:
    record = ProjectedRecord(
        role="x", nsid="pub.layers.unknown", local_id="k", uri="at://x", value_json="[]"
    )
    with pytest.raises(TypeError):
        record.value()
    with pytest.raises(ValueError, match="no record model"):
        record.to_model()


def test_duplicate_row_ids_are_rejected() -> None:
    text = "1\ta\t_\tX\t_\t_\t0\troot\t_\t_\n1\tb\t_\tX\t_\t_\t0\troot\t_\t_\n\n"
    with pytest.raises(ValueError, match="duplicate row id"):
        _records(text)
