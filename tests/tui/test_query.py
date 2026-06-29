"""Unit tests for the TUI query engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lairs.tui.query import (
    CqlError,
    QueryEngine,
    QueryError,
    QueryResult,
    QueryRow,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(directory: Path, name: str, columns: dict[str, list[object]]) -> Path:
    """Write a one-view Parquet directory and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), directory / f"{name}.parquet")
    return directory


# ---- open / registration --------------------------------------------------


def test_open_registers_views_in_order(corpus_dir: Path) -> None:
    assert QueryEngine.open(corpus_dir).tables == ("expressions", "annotations")


def test_open_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(QueryError, match="no such data directory"):
        QueryEngine.open(tmp_path / "absent")


def test_open_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(QueryError, match=r"no \.parquet"):
        QueryEngine.open(tmp_path)


def test_open_skips_unreadable_parquet(tmp_path: Path) -> None:
    # a column-less Parquet (an empty materialized view) cannot back a view; it
    # is skipped rather than failing the whole engine open.
    _write(tmp_path, "expressions", {"id": [1, 2]})
    pq.write_table(pa.table({}), tmp_path / "annotations.parquet")
    engine = QueryEngine.open(tmp_path)
    assert engine.tables == ("expressions",)
    assert engine.run_sql("SELECT COUNT(*) AS n FROM expressions").rows[0].cells == (
        "2",
    )


def test_open_raises_when_no_readable_views(tmp_path: Path) -> None:
    pq.write_table(pa.table({}), tmp_path / "annotations.parquet")
    with pytest.raises(QueryError, match="no readable"):
        QueryEngine.open(tmp_path)


def test_open_orders_preferred_then_extras(tmp_path: Path) -> None:
    for name in ("zeta", "annotations", "expressions", "segmentations"):
        pq.write_table(pa.table({"x": [1]}), tmp_path / f"{name}.parquet")
    assert QueryEngine.open(tmp_path).tables == (
        "expressions",
        "annotations",
        "segmentations",
        "zeta",
    )


def test_open_sanitizes_view_names(tmp_path: Path) -> None:
    pq.write_table(pa.table({"x": [1]}), tmp_path / "weird-name.parquet")
    engine = QueryEngine.open(tmp_path)
    assert engine.tables == ("weird_name",)
    assert engine.run_sql("SELECT x FROM weird_name").row_count == 1


# ---- schema / columns -----------------------------------------------------


def test_schema_lists_columns(corpus_dir: Path) -> None:
    schema = dict(QueryEngine.open(corpus_dir).schema())
    assert schema["expressions"] == ("id", "kind", "text")
    assert "token_index" in schema["annotations"]


def test_columns_unknown_table(corpus_dir: Path) -> None:
    assert QueryEngine.open(corpus_dir).columns("nope") == ()


# ---- run_sql --------------------------------------------------------------


def test_run_sql_aggregates(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).run_sql(
        "SELECT label, count(*) AS n FROM annotations GROUP BY label ORDER BY n DESC"
    )
    assert result.columns == ("label", "n")
    assert result.row_count == 4
    assert result.rows[0].cells[1] == "3"


def test_run_sql_truncates_at_limit(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).run_sql("SELECT * FROM annotations", limit=2)
    assert result.row_count == 2
    assert result.truncated is True


def test_run_sql_exact_count_is_not_truncated(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).run_sql("SELECT * FROM expressions", limit=3)
    assert result.row_count == 3
    assert result.truncated is False


def test_run_sql_strips_trailing_semicolon(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).run_sql("SELECT 1 AS one;  ")
    assert result.rows[0].cells == ("1",)


def test_run_sql_stringifies_cells(tmp_path: Path) -> None:
    _write(tmp_path, "t", {"a": [1, None], "b": ["x", None]})
    result = QueryEngine.open(tmp_path).run_sql(
        "SELECT a, b FROM t ORDER BY a NULLS LAST"
    )
    assert result.rows[0].cells == ("1", "x")
    assert result.rows[1].cells == ("", "")


def test_run_sql_records_elapsed(corpus_dir: Path) -> None:
    assert QueryEngine.open(corpus_dir).run_sql("SELECT 1").elapsed_ms >= 0.0


def test_run_sql_rejects_empty(corpus_dir: Path) -> None:
    with pytest.raises(QueryError, match="empty query"):
        QueryEngine.open(corpus_dir).run_sql("   ")


def test_run_sql_reports_errors(corpus_dir: Path) -> None:
    with pytest.raises(QueryError):
        QueryEngine.open(corpus_dir).run_sql("SELECT * FROM nope")


# ---- concordance ----------------------------------------------------------


def test_concordance_kwic_context(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).concordance(r"\bfox\b")
    assert result.columns == ("source", "left", "match", "right")
    assert result.row_count == 1
    source, left, match, right = result.rows[0].cells
    assert source == "s1"
    assert match == "fox"
    assert left.endswith("brown ")
    assert right.startswith(" jumps")


def test_concordance_finds_all_matches(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).concordance(r"\bdog\b")
    assert result.row_count == 3
    assert {row.cells[0] for row in result.rows} == {"s1", "s2", "s3"}


def test_concordance_respects_window(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).concordance(r"\bjumps\b", window=4)
    _, left, _, right = result.rows[0].cells
    assert len(left) <= 4
    assert len(right) <= 4


def test_concordance_case_insensitive_default(corpus_dir: Path) -> None:
    assert QueryEngine.open(corpus_dir).concordance(r"\brun\b").row_count == 2


def test_concordance_case_sensitive(corpus_dir: Path) -> None:
    engine = QueryEngine.open(corpus_dir)
    assert engine.concordance(r"\bRUN\b", ignore_case=False).row_count == 0
    assert engine.concordance(r"\bRun\b", ignore_case=False).row_count == 1


def test_concordance_collapses_whitespace(tmp_path: Path) -> None:
    _write(tmp_path, "expressions", {"id": ["a"], "text": ["one\n\ttwo HIT three"]})
    result = QueryEngine.open(tmp_path).concordance("HIT")
    _, left, _, _ = result.rows[0].cells
    assert "\n" not in left
    assert "\t" not in left
    assert left == "one two "


def test_concordance_prefers_uri_source(tmp_path: Path) -> None:
    _write(tmp_path, "t", {"uri": ["U"], "id": ["I"], "text": ["a HIT b"]})
    result = QueryEngine.open(tmp_path).concordance("HIT", table="t")
    assert result.rows[0].cells[0] == "U"


def test_concordance_single_column_table(tmp_path: Path) -> None:
    _write(tmp_path, "t", {"text": ["a HIT b"]})
    assert QueryEngine.open(tmp_path).concordance("HIT", table="t").row_count == 1


def test_concordance_over_custom_column(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).concordance(
        "dog", table="annotations", column="value"
    )
    assert result.row_count == 2


def test_concordance_unknown_column(corpus_dir: Path) -> None:
    with pytest.raises(QueryError, match="not found"):
        QueryEngine.open(corpus_dir).concordance("x", column="absent")


def test_concordance_empty_pattern(corpus_dir: Path) -> None:
    with pytest.raises(QueryError, match="empty"):
        QueryEngine.open(corpus_dir).concordance("   ")


def test_concordance_invalid_regex(corpus_dir: Path) -> None:
    with pytest.raises(QueryError, match="invalid pattern"):
        QueryEngine.open(corpus_dir).concordance("(")


def test_concordance_no_matches(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).concordance("zzzznotthere")
    assert result.row_count == 0
    assert result.truncated is False


def test_concordance_truncates(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).concordance(r"\bdog\b", limit=1)
    assert result.row_count == 1
    assert result.truncated is True


# ---- cql ------------------------------------------------------------------


def test_cql_single_token(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label="DET"]')
    assert result.columns == ("layer_uri", "token_index", "tok0")
    assert result.row_count == 3
    assert {row.cells[0] for row in result.rows} == {"L1", "L2", "L3"}


def test_cql_two_token_sequence(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label="ADJ"] [label="NOUN"]')
    assert result.row_count == 1
    assert result.rows[0].cells == ("L1", "2", "ADJ", "NOUN")


def test_cql_three_token_sequence(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql(
        '[label="DET"] [label="ADJ"] [label="ADJ"]'
    )
    assert result.columns == ("layer_uri", "token_index", "tok0", "tok1", "tok2")
    assert result.row_count == 1
    assert result.rows[0].cells[2:] == ("DET", "ADJ", "ADJ")


def test_cql_does_not_cross_layers(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label="VERB"] [label="DET"]')
    assert result.row_count == 0


def test_cql_gap_breaks_sequence(corpus_dir: Path) -> None:
    # only L2 has adjacent DET, NOUN; L3 has a gap, L1 has ADJ after DET.
    result = QueryEngine.open(corpus_dir).cql('[label="DET"] [label="NOUN"]')
    assert result.row_count == 1
    assert result.rows[0].cells[0] == "L2"


def test_cql_regex_operator(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label~"^A"]')
    assert {row.cells[2] for row in result.rows} == {"ADJ"}
    assert result.row_count == 2


def test_cql_negation_operator(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label!="ADJ"]')
    labels = {row.cells[2] for row in result.rows}
    assert "ADJ" not in labels
    assert {"DET", "NOUN", "VERB"} <= labels


def test_cql_any_token(corpus_dir: Path) -> None:
    assert QueryEngine.open(corpus_dir).cql("[]").row_count == 9


def test_cql_conjunction_with_ampersand(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label="DET" & subkind="pos"]')
    assert result.row_count == 3


def test_cql_conjunction_with_whitespace(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label="DET" subkind="pos"]')
    assert result.row_count == 3


def test_cql_value_attribute(corpus_dir: Path) -> None:
    assert QueryEngine.open(corpus_dir).cql('[value="dog"]').row_count == 2


def test_cql_unsatisfiable_conjunction(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql('[label="DET" & label="NOUN"]')
    assert result.row_count == 0


def test_cql_unknown_attribute(corpus_dir: Path) -> None:
    with pytest.raises(CqlError, match="unknown attribute"):
        QueryEngine.open(corpus_dir).cql('[bogus="x"]')


def test_cql_malformed(corpus_dir: Path) -> None:
    with pytest.raises(CqlError, match="malformed"):
        QueryEngine.open(corpus_dir).cql("[label=VERB]")


def test_cql_requires_blocks(corpus_dir: Path) -> None:
    with pytest.raises(CqlError, match="no token blocks"):
        QueryEngine.open(corpus_dir).cql('label="VERB"')


def test_cql_rejects_non_token_aligned(tmp_path: Path) -> None:
    _write(tmp_path, "x", {"id": ["s1"], "text": ["hello"]})
    with pytest.raises(CqlError, match="not token-aligned"):
        QueryEngine.open(tmp_path).cql('[label="X"]', table="x")


def test_cql_escapes_quotes_in_value(corpus_dir: Path) -> None:
    # a single quote in the value must not break the SQL; it simply matches nothing.
    assert QueryEngine.open(corpus_dir).cql('[value="O\'Brien"]').row_count == 0


def test_cql_without_label_column(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "ann",
        {"layer_uri": ["L", "L"], "token_index": [0, 1], "pos": ["DET", "NOUN"]},
    )
    result = QueryEngine.open(tmp_path).cql('[pos="DET"]', table="ann")
    assert result.columns == ("layer_uri", "token_index")
    assert result.row_count == 1


def test_cql_truncates(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).cql("[]", limit=2)
    assert result.row_count == 2
    assert result.truncated is True


@pytest.mark.parametrize("quantifier", ["*", "+", "?", "{2}"])
def test_cql_rejects_repetition_quantifier(corpus_dir: Path, quantifier: str) -> None:
    # an unsupported quantifier must fail loudly, not be silently dropped and run
    # the block as a single required token.
    query = f'[label="DET"] [label="ADJ"]{quantifier} [label="NOUN"]'
    with pytest.raises(CqlError, match="quantifier"):
        QueryEngine.open(corpus_dir).cql(query)


def test_cql_quantifier_rejected_before_running(corpus_dir: Path) -> None:
    # the documented [DET] [ADJ]* [NOUN] example is rejected rather than treated
    # as three mandatory tokens (which would wrongly match L1's DET ADJ ... ADJ).
    with pytest.raises(CqlError, match="not supported"):
        QueryEngine.open(corpus_dir).cql('[label="DET"] [label="ADJ"]* [label="NOUN"]')


# ---- result models / lifecycle -------------------------------------------


def test_query_result_round_trips(corpus_dir: Path) -> None:
    result = QueryEngine.open(corpus_dir).run_sql("SELECT id FROM expressions")
    restored = QueryResult.model_validate_json(result.model_dump_json())
    assert restored.columns == result.columns
    assert restored.rows[0].cells == result.rows[0].cells
    assert isinstance(restored.rows[0], QueryRow)


def test_close_closes_connection(corpus_dir: Path) -> None:
    engine = QueryEngine.open(corpus_dir)
    engine.close()
    with pytest.raises(QueryError):
        engine.run_sql("SELECT 1")
