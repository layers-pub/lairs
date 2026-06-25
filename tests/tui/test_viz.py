"""Model-driven tests for the annotation/judgment visualizers.

These exercise the visualizers on SYNTHETIC records constructed straight from
the lexicon's type system, so coverage is model-complete rather than tied to the
four reference corpora: every anchor variant, the token-aligned views, the span
/ tier / graph / document-tag renderers, and one judgment view per ``taskType``.
"""

from __future__ import annotations

from lairs.tui import viz


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
    nodes = {"at://n/1": {"label": "eat"}, "at://n/2": {"label": "apple"}}
    edges = [
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


def _judgments(field: str, values: list) -> list[dict]:
    """Build judgment dicts populating one response field."""
    return [{field: value} for value in values]


def test_ordinal_scale_likert() -> None:
    experiment = {
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
    experiment = {
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
    experiment = {"measureType": "preference", "taskType": "forced-choice"}
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["A", "A", "B", "A"])
    )
    assert "forced-choice" in out
    assert "A" in out
    assert "75%" in out


def test_odd_man_out_marks_outlier() -> None:
    experiment = {"measureType": "similarity", "taskType": "forced-choice"}
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["x3", "x3", "x1", "x3", "x2"])
    )
    assert "x3" in out
    assert "60%" in out


def test_binary_distribution() -> None:
    experiment = {"measureType": "comprehension", "taskType": "binary"}
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["yes", "no", "yes"])
    )
    assert "yes" in out
    assert "no" in out


def test_categorical_distribution() -> None:
    experiment = {"measureType": "production", "taskType": "categorical"}
    out = viz.judgment_distribution(
        experiment, _judgments("categoricalValue", ["pos", "neg", "pos", "neu"])
    )
    assert "pos" in out
    assert "neg" in out


def test_free_text_lists_responses() -> None:
    experiment = {"measureType": "production", "taskType": "free-text"}
    out = viz.judgment_distribution(
        experiment,
        _judgments("freeText", ["A believed C", "A believed C", "C is true"]),
    )
    assert "A believed C" in out


def test_unknown_task_falls_back_to_scalar() -> None:
    experiment = {"measureType": "custom", "taskType": "reaction-norming"}
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
