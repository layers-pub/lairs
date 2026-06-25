"""Model-driven tests for the annotation/judgment visualizers.

These exercise the visualizers on SYNTHETIC records constructed straight from
the lexicon's type system, so coverage is model-complete rather than tied to the
four reference corpora: every anchor variant, the token-aligned views, the span
/ tier / graph / document-tag renderers, and one judgment view per ``taskType``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.tui import viz
from lairs.tui.browse import RepoBrowser

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from lairs._types import JsonValue

_S1 = "at://did:plc:browsefixture/pub.layers.expression.expression/s1"
_SEG = "at://did:plc:browsefixture/pub.layers.segmentation.segmentation/seg1"
_POS_LAYER = "at://did:plc:browsefixture/pub.layers.annotation.annotationLayer/al1"
_DEP_LAYER = "at://did:plc:browsefixture/pub.layers.annotation.annotationLayer/al2"


def _syntax() -> viz.Syntax:
    """Build a four-token sentence with POS tags and a dependency parse."""
    tokens = [
        viz.Token(0, "The", 0, 3),
        viz.Token(1, "dog", 4, 7),
        viz.Token(2, "runs", 8, 12),
        viz.Token(3, ".", 12, 13),
    ]
    tags = {"UPOS": {0: "DET", 1: "NOUN", 2: "VERB", 3: "PUNCT"}}
    deps = {0: (1, "det"), 1: (2, "nsubj"), 2: (-1, "root"), 3: (2, "punct")}
    return viz.Syntax(tokens, ["UPOS"], tags, deps, "tok")


# ---- anchor resolution over the full union ---------------------------------


def test_anchor_token_indexes_variants() -> None:
    assert viz.anchor_token_indexes({"tokenRef": {"tokenIndex": 3}}) == [3]
    assert viz.anchor_token_indexes(
        {"tokenRefSequence": {"tokenIndexes": [1, 2, 4]}}
    ) == [1, 2, 4]
    assert viz.anchor_token_indexes({"textSpan": {"byteStart": 0, "byteEnd": 4}}) == []


def test_anchor_summary_covers_every_variant() -> None:
    assert viz.anchor_summary({"tokenRef": {"tokenIndex": 5}}) == "token 5"
    assert (
        viz.anchor_summary({"textSpan": {"byteStart": 0, "byteEnd": 4}}) == "bytes 0..4"
    )
    assert (
        viz.anchor_summary({"temporalSpan": {"start": 1000, "ending": 2500}})
        == "1.00..2.50s"
    )
    assert viz.anchor_summary({"pageAnchor": {"page": 2}}) == "page 2"
    assert "external" in viz.anchor_summary(
        {"externalTarget": {"source": "https://example.org"}}
    )
    assert viz.anchor_summary({}) == "(no anchor)"


# ---- token-aligned views ----------------------------------------------------


def test_conllu_grid_has_columns_and_rows() -> None:
    grid = viz.conllu_grid(_syntax())
    assert "UPOS" in grid
    assert "HEAD" in grid
    assert "DEPREL" in grid
    assert "runs" in grid
    assert "root" in grid


def test_dependency_tree_nests_by_head() -> None:
    tree = viz.dependency_tree(_syntax())
    assert "runs  (root)" in tree
    assert "├─ dog  (nsubj)" in tree
    assert "└─ The  (det)" in tree or "├─ The  (det)" in tree


def test_interlinear_aligns_tags_under_tokens() -> None:
    tokens = _syntax().tokens
    out = viz.interlinear(tokens, [("UPOS", {0: "DET", 1: "NOUN", 2: "VERB"})])
    assert "The" in out
    assert "DET" in out
    assert "word" in out


# ---- span / tier / graph / document-tag ------------------------------------


def test_span_overlay_underlines_and_labels() -> None:
    out = viz.span_overlay("Mary met Bob.", [(0, 4, "PER"), (9, 12, "PER")])
    assert "Mary met Bob." in out
    assert "PER" in out
    assert "▔" in out


def test_tier_timeline_lays_out_lanes() -> None:
    out = viz.tier_timeline(
        [
            ("words", [(0, 600, "hi"), (600, 1200, "there")]),
            ("gesture", [(700, 1000, "wave")]),
        ],
        ms_per_col=200,
    )
    assert "words" in out
    assert "gesture" in out
    assert "hi" in out


def test_graph_edges_resolve_node_labels() -> None:
    nodes: Mapping[str, Mapping[str, JsonValue]] = {
        "at://n/1": {"label": "eat"},
        "at://n/2": {"label": "apple"},
    }
    edges: list[Mapping[str, JsonValue]] = [
        {
            "source": {"recordRef": "at://n/1"},
            "target": {"recordRef": "at://n/2"},
            "edgeType": "related-to",
            "label": "ARG1",
        }
    ]
    out = viz.graph_edges(nodes, edges)
    assert "eat  --related-to/ARG1-->  apple" in out


def test_document_tags_render_chips_with_confidence() -> None:
    out = viz.document_tags(
        [{"label": "positive", "confidence": 820}, {"label": "formal"}]
    )
    assert "[ positive 82% ]" in out
    assert "[ formal ]" in out


# ---- judgment distribution: one assertion per taskType ---------------------


def _judgments(field: str, values: list[JsonValue]) -> list[Mapping[str, JsonValue]]:
    """Build judgment dicts populating one response field."""
    return [{field: value} for value in values]


def test_ordinal_scale_likert() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "acceptability",
        "taskType": "ordinal-scale",
        "scaleMin": 1,
        "scaleMax": 7,
    }
    out = viz.judgment_distribution(
        experiment, _judgments("scalarValue", [7, 7, 6, 5, 7, 3, 7])
    )
    assert "ordinal-scale" in out
    assert "mean" in out
    assert "median" in out


def test_magnitude_uses_geometric_mean() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "inference",
        "taskType": "magnitude",
        "scaleMin": 0,
        "scaleMax": 1000,
    }
    out = viz.judgment_distribution(
        experiment, _judgments("scalarValue", [750, 820, 400, 900, 300])
    )
    assert "geo-mean" in out


def test_forced_choice_2afc_proportions() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "preference",
        "taskType": "forced-choice",
    }
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["A", "A", "B", "A"])
    )
    assert "forced-choice" in out
    assert "A" in out
    assert "75%" in out


def test_odd_man_out_marks_outlier() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "similarity",
        "taskType": "forced-choice",
    }
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["x3", "x3", "x1", "x3", "x2"])
    )
    assert "x3" in out
    assert "60%" in out


def test_binary_distribution() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "comprehension",
        "taskType": "binary",
    }
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["yes", "no", "yes"])
    )
    assert "yes" in out
    assert "no" in out


def test_categorical_distribution() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "production",
        "taskType": "categorical",
    }
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["pos", "neg", "pos", "neu"])
    )
    assert "pos" in out
    assert "neg" in out


def test_free_text_lists_responses() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "production",
        "taskType": "free-text",
    }
    out = viz.judgment_distribution(
        experiment,
        _judgments("freeText", ["A believed C", "A believed C", "C is true"]),
    )
    assert "A believed C" in out


def test_unknown_task_falls_back_to_scalar() -> None:
    experiment: Mapping[str, JsonValue] = {
        "measureType": "custom",
        "taskType": "reaction-norming",
    }
    out = viz.judgment_distribution(experiment, _judgments("scalarValue", [4, 5, 4, 6]))
    assert "mean" in out


def test_empty_judgments_is_safe() -> None:
    out = viz.judgment_distribution({"taskType": "ordinal-scale"}, [])
    assert "No responses" in out


# ---- primitives -------------------------------------------------------------


def test_sparkline_scales_to_peak() -> None:
    assert viz.sparkline([0, 1, 2, 4, 8]).endswith("█")
    assert viz.sparkline([]) == ""


def test_anchor_time_span_reads_temporal() -> None:
    assert viz.anchor_time_span({"temporalSpan": {"start": 100, "ending": 900}}) == (
        100,
        900,
    )
    assert viz.anchor_time_span({"tokenRef": {"tokenIndex": 0}}) is None


def test_hbar_scales_and_clamps() -> None:
    assert viz.hbar(0, 0) == ""
    assert len(viz.hbar(4, 4, width=10)) == 10
    assert len(viz.hbar(2, 4, width=10)) == 5
    assert viz.hbar(0, 4, width=10) == ""


def test_pack_lanes_separates_overlaps_and_shares_disjoint() -> None:
    # two disjoint spans share lane 0; an overlapping span takes a separate lane.
    lanes = viz._pack_lanes([(0, 4), (5, 9), (2, 7)])
    assert lanes[0] == lanes[1]
    assert lanes[2] != lanes[0]


def test_feature_map_flattens_entries() -> None:
    value: JsonValue = {
        "entries": [{"key": "tense", "value": "past"}, {"key": "num", "value": "sg"}]
    }
    assert viz.feature_map(value) == {"tense": "past", "num": "sg"}
    assert viz.feature_map({}) == {}


def test_anchor_byte_span_text_and_page_and_none() -> None:
    assert viz.anchor_byte_span({"textSpan": {"byteStart": 4, "byteEnd": 9}}) == (4, 9)
    assert viz.anchor_byte_span(
        {"pageAnchor": {"page": 1, "textSpan": {"byteStart": 0, "byteEnd": 3}}}
    ) == (0, 3)
    assert viz.anchor_byte_span({"tokenRef": {"tokenIndex": 0}}) is None


def test_anchor_tokenization_reads_token_anchors() -> None:
    anchor: JsonValue = {
        "tokenRef": {"tokenIndex": 0, "tokenizationId": {"value": "tok/x"}}
    }
    assert viz.anchor_tokenization(anchor) == "tok/x"
    seq: JsonValue = {
        "tokenRefSequence": {"tokenIndexes": [0, 1], "tokenizationId": {"value": "t"}}
    }
    assert viz.anchor_tokenization(seq) == "t"
    assert viz.anchor_tokenization({"textSpan": {"byteStart": 0, "byteEnd": 1}}) == ""


# ---- ordinal histogram consistency (out-of-range + even-n median) ----------


def test_ordinal_counts_out_of_range_responses() -> None:
    # a response of 5 outside a declared 1..3 scale must still be counted in the
    # bars and the n, not silently dropped while inflating the mean.
    experiment: Mapping[str, JsonValue] = {
        "measureType": "acceptability",
        "taskType": "ordinal-scale",
        "scaleMin": 1,
        "scaleMax": 3,
    }
    out = viz.judgment_distribution(experiment, _judgments("scalarValue", [5, 2]))
    assert "n 2" in out
    assert "  5  " in out  # a bar exists for level 5
    assert "mean 3.5" in out


def test_ordinal_even_n_median_is_average_of_middles() -> None:
    out = viz._ordinal({"scaleMin": 1, "scaleMax": 7}, [2, 4])
    assert "median 3" in out  # (2 + 4) / 2, not the upper middle (4)


def test_ordinal_odd_n_median() -> None:
    out = viz._ordinal({"scaleMin": 1, "scaleMax": 7}, [2, 4, 6])
    assert "median 4" in out


# ---- byte-boundary fallback snaps instead of spanning the whole text -------


def test_byte_to_char_at_exact_and_off_boundary() -> None:
    text = "café"  # 'é' is two UTF-8 bytes at byte offset 3..5
    byte_char = viz._byte_to_char(text)
    assert viz._byte_to_char_at(byte_char, 3, len(text)) == 3  # exact boundary
    # offset 4 lands inside 'é'; it snaps to the codepoint start (char 3),
    # not to len(text) which would stretch a span across the whole string.
    assert viz._byte_to_char_at(byte_char, 4, len(text)) == 3


# ---- browser-backed views over the real seeded repository ------------------


def test_tokenizations_of_reads_real_segmentation(repo_dir: Path) -> None:
    browser = RepoBrowser.open(repo_dir)
    toks = viz.tokenizations_of(browser, _S1)
    assert "tok/s1/words" in toks
    forms = [t.text for t in toks["tok/s1/words"]]
    assert forms == ["The", "quick", "brown", "fox", "jumps", "."]


def test_segmentation_tokens_renders_table(repo_dir: Path) -> None:
    browser = RepoBrowser.open(repo_dir)
    seg = dict(browser.records_raw("pub.layers.segmentation.segmentation"))[_SEG]
    out = viz.segmentation_tokens(browser, seg)
    assert "penn-treebank" in out
    assert "brown" in out
    assert "16..19" in out  # the byte range of "fox"


def test_assemble_syntax_merges_pos_and_dependencies(repo_dir: Path) -> None:
    browser = RepoBrowser.open(repo_dir)
    syntax = viz.assemble_syntax(browser, _S1)
    assert syntax is not None
    assert "UPOS" in syntax.columns
    assert syntax.tags["UPOS"][3] == "NOUN"
    assert syntax.deps[3] == (4, "nsubj")


def test_single_dep_syntax_holds_one_layer(repo_dir: Path) -> None:
    browser = RepoBrowser.open(repo_dir)
    layer = dict(browser.records_raw("pub.layers.annotation.annotationLayer"))[
        _DEP_LAYER
    ]
    syntax = viz.single_dep_syntax(browser, _S1, layer)
    assert syntax is not None
    assert syntax.columns == []
    assert syntax.deps[3] == (4, "nsubj")


def test_token_tag_interlinear_aligns_tags(repo_dir: Path) -> None:
    browser = RepoBrowser.open(repo_dir)
    layer = dict(browser.records_raw("pub.layers.annotation.annotationLayer"))[
        _POS_LAYER
    ]
    out = viz.token_tag_interlinear(browser, _S1, layer)
    assert "fox" in out
    assert "NOUN" in out


def test_span_layer_overlay_positions_byte_spans(repo_dir: Path) -> None:
    # a real span-kind layer with byte-anchored annotations over s1's text.
    browser = RepoBrowser.open(repo_dir)
    layer: Mapping[str, JsonValue] = {
        "kind": "span",
        "annotations": [
            {
                "label": "ANIMAL",
                "anchor": {"textSpan": {"byteStart": 16, "byteEnd": 19}},
            }
        ],
    }
    out = viz.span_layer_overlay(browser, _S1, layer)
    assert "The quick brown fox jumps." in out
    assert "ANIMAL" in out
    assert "▔" in out


def test_alignment_bitext_links_source_to_target(repo_dir: Path) -> None:
    browser = RepoBrowser.open(repo_dir)
    data: Mapping[str, JsonValue] = {
        "expression": _S1,
        "source": {"localId": {"value": "tok/s1/words"}},
        "target": {"localId": {"value": "tok/s1/words"}},
        "links": [
            {"sourceIndices": [3], "targetIndices": [3], "label": "same"},
        ],
    }
    out = viz.alignment_bitext(browser, data)
    assert "3:fox" in out
    assert "--same-->" in out


def test_alignment_bitext_no_links(repo_dir: Path) -> None:
    browser = RepoBrowser.open(repo_dir)
    out = viz.alignment_bitext(browser, {"expression": _S1, "links": []})
    assert "no links" in out
