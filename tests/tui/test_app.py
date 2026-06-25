"""Pilot-driven tests for the lairs explorer app.

Textual's ``App.run_test`` is async; each test drives it through ``asyncio.run``
so the suite needs no async-pytest plugin.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from textual.widgets import DataTable, Input, RadioSet, TabbedContent, TextArea, Tree

from lairs.discovery.cards import CardFreshness, CardProvenance, DatasetCard
from lairs.discovery.models import DatasetSummary
from lairs.tui.app import HelpScreen, LairsApp
from lairs.tui.query import QueryError
from lairs.tui.screens.explore import (
    ExplorePane,
    _card_markdown,
    _int_or_none,
    _languages,
    _none_if_blank,
)
from lairs.tui.screens.query import QueryPane

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 6, 18, tzinfo=UTC)


def _card(name: str, **facets: str | None) -> DatasetCard:
    """Build a minimal dataset card for the pure-helper tests."""
    language = facets.get("language")
    summary = DatasetSummary(
        uri=f"at://did:plc:x/pub.layers.corpus.corpus/{name}",
        did="did:plc:x",
        name=name,
        domain=facets.get("domain"),
        language=language,
        languages=(language,) if language else (),
        license=facets.get("license_id"),
        description=facets.get("description"),
    )
    return DatasetCard(
        summary=summary,
        provenance=CardProvenance(
            source_did="did:plc:x",
            source_endpoint="https://pds.example",
            discovered_via="seed",
        ),
        freshness=CardFreshness(first_seen_at=_NOW, last_updated_at=_NOW),
    )


# ---- explore helpers (pure) ----------------------------------------------


def test_int_or_none() -> None:
    assert _int_or_none("  42 ") == 42
    assert _int_or_none("") is None
    assert _int_or_none("nope") is None


def test_none_if_blank() -> None:
    assert _none_if_blank("  x ") == "x"
    assert _none_if_blank("   ") is None


def test_languages_prefers_list() -> None:
    card = _card("c", language="en")
    assert _languages(card) == "en"


def test_card_markdown_includes_facets() -> None:
    card = _card("Demo", domain="legal", license_id="CC-BY-4.0", description="a corpus")
    md = _card_markdown(card)
    assert "# Demo" in md
    assert "a corpus" in md
    assert "CC-BY-4.0" in md
    assert "legal" in md
    assert card.summary.uri in md


# ---- app shell ------------------------------------------------------------


def test_app_boots_empty() -> None:
    async def scenario() -> None:
        app = LairsApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.theme == "tokyo-night"
            assert app.query_one("#results", DataTable).row_count == 0

    asyncio.run(scenario())


def test_tab_keybindings_switch() -> None:
    async def scenario() -> None:
        app = LairsApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            assert app.query_one(TabbedContent).active == "query"
            await pilot.press("2")
            await pilot.pause()
            assert app.query_one(TabbedContent).active == "browse"
            await pilot.press("1")
            await pilot.pause()
            assert app.query_one(TabbedContent).active == "explore"

    asyncio.run(scenario())


def test_help_modal_opens_and_closes() -> None:
    async def scenario() -> None:
        app = LairsApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    asyncio.run(scenario())


def test_theme_cycles() -> None:
    async def scenario() -> None:
        app = LairsApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            first = app.theme
            app.action_cycle_theme()
            await pilot.pause()
            assert app.theme != first

    asyncio.run(scenario())


# ---- explore tab ----------------------------------------------------------


def test_explore_lists_datasets(index_path: str) -> None:
    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.query_one("#results", DataTable).row_count == 3

    asyncio.run(scenario())


def test_explore_filters_by_domain(index_path: str) -> None:
    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one("#f_domain", Input).value = "legal"
            await pilot.pause()
            assert app.query_one("#results", DataTable).row_count == 1

    asyncio.run(scenario())


def test_explore_filters_by_text(index_path: str) -> None:
    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one("#f_text", Input).value = "climate"
            await pilot.pause()
            assert app.query_one("#results", DataTable).row_count == 1

    asyncio.run(scenario())


def test_explore_filters_by_min_expressions(index_path: str) -> None:
    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one("#f_min", Input).value = "50"
            await pilot.pause()
            assert app.query_one("#results", DataTable).row_count == 2

    asyncio.run(scenario())


def test_explore_empty_index_shows_guidance() -> None:
    async def scenario() -> None:
        app = LairsApp()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            pane = app.query_one(ExplorePane)
            assert pane._error is not None
            assert app.query_one("#results", DataTable).row_count == 0

    asyncio.run(scenario())


def test_explore_highlight_tracks_cards(index_path: str) -> None:
    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            pane = app.query_one(ExplorePane)
            assert len(pane._hits) == 3

    asyncio.run(scenario())


# ---- query tab ------------------------------------------------------------


def _select_mode(app: LairsApp, mode: int) -> None:
    """Select a query mode radio button by index."""
    app.query_one("#mode", RadioSet).query("RadioButton")[mode].value = True


def test_query_schema_tree_populated(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            tree = app.query_one("#schema", Tree)
            table_labels = [str(node.label) for node in tree.root.children]
            assert any("expressions" in label for label in table_labels)
            assert any("annotations" in label for label in table_labels)

    asyncio.run(scenario())


def test_query_tree_node_inserts_into_editor(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            editor = app.query_one("#editor", TextArea)
            editor.text = ""
            tree = app.query_one("#schema", Tree)
            column_node = tree.root.children[0].children[0]
            pane.on_tree_node_selected(Tree.NodeSelected(column_node))
            await pilot.pause()
            assert editor.text.strip() == str(column_node.data)

    asyncio.run(scenario())


def test_query_schema_insert_appends_after_starter(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            editor = app.query_one("#editor", TextArea)
            starter = editor.text
            assert starter.startswith("SELECT")
            column_node = app.query_one("#schema", Tree).root.children[0].children[0]
            name = str(column_node.data)
            pane.on_tree_node_selected(Tree.NodeSelected(column_node))
            pane.on_tree_node_selected(Tree.NodeSelected(column_node))
            await pilot.pause()
            # the inserted names land after the starter, space-separated, never
            # fused or prepended ahead of SELECT.
            assert editor.text == f"{starter} {name} {name} "

    asyncio.run(scenario())


def test_query_run_button_runs(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            app.query_one("#editor", TextArea).text = "SELECT id FROM expressions"
            await pilot.click("#run")
            await pilot.pause()
            assert app.query_one("#qresults", DataTable).row_count == 3

    asyncio.run(scenario())


def test_query_modes_render_results(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            results = app.query_one("#qresults", DataTable)

            _select_mode(app, 1)
            await pilot.pause()
            app.query_one("#editor", TextArea).text = r"\bfox\b"
            pane.action_run()
            await pilot.pause()
            assert [str(c.label) for c in results.columns.values()] == [
                "source",
                "left",
                "match",
                "right",
            ]
            assert results.row_count == 1

            _select_mode(app, 2)
            await pilot.pause()
            app.query_one("#editor", TextArea).text = '[label="ADJ"] [label="NOUN"]'
            pane.action_run()
            await pilot.pause()
            assert results.row_count == 1

    asyncio.run(scenario())


def test_query_mode_switch_seeds_empty_editor(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            editor.text = ""
            _select_mode(app, 1)
            await pilot.pause()
            assert "\\b" in editor.text  # the concordance starter

    asyncio.run(scenario())


def test_query_sql_starter_uses_first_table(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            # the SQL starter targets the first materialized view, not a
            # hardcoded corpus table.
            assert "FROM expressions" in app.query_one("#editor", TextArea).text

    asyncio.run(scenario())


def test_query_error_does_not_crash(corpus_dir: Path) -> None:
    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            app.query_one("#editor", TextArea).text = "SELECT * FROM does_not_exist"
            pane.action_run()
            await pilot.pause()
            assert app.query_one("#qresults", DataTable).row_count == 0

    asyncio.run(scenario())


def test_query_without_corpus_is_inert() -> None:
    async def scenario() -> None:
        app = LairsApp()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            assert pane._engine is None
            app.query_one("#editor", TextArea).text = "SELECT 1"
            pane.action_run()
            await pilot.pause()
            assert app.query_one("#qresults", DataTable).row_count == 0

    asyncio.run(scenario())


def test_query_pane_closes_engine_on_unmount(corpus_dir: Path) -> None:
    """Unmounting the Query pane closes its DuckDB connection (no leak)."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            engine = pane._engine
            assert engine is not None
            pane.on_unmount()
            # the engine is released and its connection is closed.
            assert pane._engine is None
            with pytest.raises(QueryError):
                engine.run_sql("SELECT 1")

    asyncio.run(scenario())
