"""Interaction-level (Pilot-driven) tests for the explorer TUI.

These drive the app the way a person does -- key presses, focus, view cycling,
query execution, and adversarial record content -- to catch the interaction
gotchas that pure-function tests miss: cursor-relative insertion, Rich-markup
leakage in tables and status lines, view-mode resets, and query error handling.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import DataTable, RadioSet, Static, TabbedContent, TextArea, Tree

from lairs.tui.app import LairsApp
from lairs.tui.screens.browse import BrowsePane
from lairs.tui.screens.query import QueryPane

if TYPE_CHECKING:
    from pathlib import Path


# ---- helpers ---------------------------------------------------------------


def _browse_leaves(app: LairsApp) -> list[Tree.NodeID]:
    """Return the Browse type-tree leaf nodes."""
    tree = app.query_one("#types", Tree)
    return [leaf for ns in tree.root.children for leaf in ns.children]


def _browse_select(app: LairsApp, nsid: str) -> None:
    """Select a record type in the Browse tree by NSID."""
    leaf = next(leaf for leaf in _browse_leaves(app) if leaf.data == nsid)
    app.query_one(BrowsePane).on_tree_node_selected(Tree.NodeSelected(leaf))


def _set_mode(app: LairsApp, index: int) -> None:
    """Select a Query mode radio button by index."""
    app.query_one("#mode", RadioSet).query("RadioButton")[index].value = True


def _first_column_node(app: LairsApp) -> Tree.NodeID:
    """Return the first column node under the first table in the schema tree."""
    return app.query_one("#schema", Tree).root.children[0].children[0]


# ---- Browse: drive every view of every record type -------------------------


def test_browse_drives_every_view_without_error(repo_dir: Path) -> None:
    """Cycle every view of several records of every type; nothing may raise."""

    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause()
            pane = app.query_one(BrowsePane)
            wrap = app.query_one("#rdetail-wrap", VerticalScroll)
            detail = app.query_one("#rdetail")
            visited = 0
            for leaf in _browse_leaves(app):
                pane.on_tree_node_selected(Tree.NodeSelected(leaf))
                await pilot.pause()
                table = app.query_one("#records", DataTable)
                for _ in range(min(table.row_count, 4)):
                    for _ in range(len(pane._views)):
                        title = str(wrap.border_title)
                        # the title is built from fixed labels only: a stray
                        # bracket would mean leaked Rich markup.
                        assert "[" not in title
                        assert "]" not in title
                        assert detail._markdown.strip()
                        visited += 1
                        await pilot.press("v")
                        await pilot.pause()
                    await pilot.press("down")
                    await pilot.pause()
            assert visited > 30  # we genuinely exercised many record/view pairs

    asyncio.run(scenario())


def test_browse_view_cycle_wraps_and_resets(repo_dir: Path) -> None:
    """`v` advances and wraps, `V` reverses, and switching types resets to 0."""

    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause()
            pane = app.query_one(BrowsePane)
            wrap = app.query_one("#rdetail-wrap", VerticalScroll)
            _browse_select(app, "pub.layers.segmentation.segmentation")
            await pilot.pause()
            assert pane._mode == 0
            assert "Tokens" in str(wrap.border_title)
            await pilot.press("v")
            await pilot.pause()
            assert pane._mode == 1
            assert "Detail" in str(wrap.border_title)
            await pilot.press("v")  # wraps back to the first view
            await pilot.pause()
            assert pane._mode == 0
            await pilot.press("V")  # reverse wraps to the last view
            await pilot.pause()
            assert pane._mode == 1
            _browse_select(app, "pub.layers.media.media")
            await pilot.pause()
            assert pane._mode == 0  # a new type resets the view

    asyncio.run(scenario())


def test_browse_single_view_record_ignores_cycle(repo_dir: Path) -> None:
    """A record with one view does not move when `v` is pressed."""

    async def scenario() -> None:
        app = LairsApp(repo_path=str(repo_dir))
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause()
            pane = app.query_one(BrowsePane)
            _browse_select(app, "pub.layers.resource.entry")
            await pilot.pause()
            assert len(pane._views) == 1
            await pilot.press("v")
            await pilot.pause()
            assert pane._mode == 0

    asyncio.run(scenario())


def test_browse_treats_record_content_as_literal(markup_repo: Path) -> None:
    """Bracket / markup characters in record fields render as literal text."""

    async def scenario() -> None:
        app = LairsApp(repo_path=str(markup_repo))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            _browse_select(app, "pub.layers.corpus.corpus")
            await pilot.pause()
            table = app.query_one("#records", DataTable)
            cell = table.get_cell_at((0, 0))
            assert isinstance(cell, Text)
            assert cell.plain == "[bold]Tricky[/bold]"
            detail = app.query_one("#rdetail")
            assert "Tricky" in detail._markdown

    asyncio.run(scenario())


def test_browse_renders_markup_expression_text(markup_repo: Path) -> None:
    """An expression whose text holds brackets renders without breaking."""

    async def scenario() -> None:
        app = LairsApp(repo_path=str(markup_repo))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            _browse_select(app, "pub.layers.expression.expression")
            await pilot.pause()
            detail = app.query_one("#rdetail")
            assert "[1]" in detail._markdown
            assert "[/red]" in detail._markdown

    asyncio.run(scenario())


# ---- Query: insertion, execution, errors, mode handling --------------------


def test_query_insert_honors_cursor_position(corpus_dir: Path) -> None:
    """Inserting a schema name lands at the cursor with token spacing."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            editor = app.query_one("#editor", TextArea)
            editor.text = "SELECT  FROM expressions"
            editor.move_cursor((0, 7))  # immediately after "SELECT "
            node = _first_column_node(app)
            pane.on_tree_node_selected(Tree.NodeSelected(node))
            await pilot.pause()
            name = str(node.data)
            expected = f"SELECT {name}  FROM expressions"  # noqa: S608 - assertion
            assert editor.text == expected

    asyncio.run(scenario())


def test_query_insert_spaces_against_word_boundary(corpus_dir: Path) -> None:
    """Inserting next to a word adds a separating space, never fusing tokens."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            editor = app.query_one("#editor", TextArea)
            editor.text = "SELECT id"
            editor.move_cursor(editor.document.end)
            node = _first_column_node(app)
            pane.on_tree_node_selected(Tree.NodeSelected(node))
            await pilot.pause()
            assert editor.text == f"SELECT id {node.data} "

    asyncio.run(scenario())


def test_query_runs_all_three_modes(corpus_dir: Path) -> None:
    """SQL, concordance, and CQL each execute and populate the results table."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            editor = app.query_one("#editor", TextArea)
            results = app.query_one("#qresults", DataTable)

            editor.text = "SELECT id FROM expressions"
            pane.action_run()
            await pilot.pause()
            assert results.row_count == 3

            _set_mode(app, 1)
            await pilot.pause()
            editor.text = r"\bdog\b"
            pane.action_run()
            await pilot.pause()
            assert results.row_count >= 1

            _set_mode(app, 2)
            await pilot.pause()
            editor.text = '[label="NOUN"]'
            pane.action_run()
            await pilot.pause()
            assert results.row_count >= 1

    asyncio.run(scenario())


def test_query_invalid_sql_shows_error_without_crashing(corpus_dir: Path) -> None:
    """A bad query clears results and shows an error status, never raising."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            app.query_one("#editor", TextArea).text = "SELECT nope FROM expressions"
            pane.action_run()
            await pilot.pause()
            assert app.query_one("#qresults", DataTable).row_count == 0
            status = str(app.query_one("#qstatus", Static).content)
            assert status.strip()

    asyncio.run(scenario())


def test_query_status_escapes_markup(corpus_dir: Path) -> None:
    """A status message containing brackets is escaped, not parsed as markup."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            pane._set_status("error near [bracket] x", error=True)
            await pilot.pause()
            status = str(app.query_one("#qstatus", Static).content)
            assert "\\[bracket]" in status

    asyncio.run(scenario())


def test_query_result_cells_are_literal(corpus_dir: Path) -> None:
    """Result cells are literal Text, not markup-interpreted strings."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            pane = app.query_one(QueryPane)
            app.query_one(
                "#editor", TextArea
            ).text = "SELECT '[x]' AS c FROM expressions LIMIT 1"
            pane.action_run()
            await pilot.pause()
            cell = app.query_one("#qresults", DataTable).get_cell_at((0, 0))
            assert isinstance(cell, Text)
            assert cell.plain == "[x]"

    asyncio.run(scenario())


def test_query_mode_switch_preserves_edits(corpus_dir: Path) -> None:
    """Switching modes never clobbers text the user has already typed."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            editor.text = "SELECT my_edit"
            _set_mode(app, 1)
            await pilot.pause()
            assert editor.text == "SELECT my_edit"

    asyncio.run(scenario())


def test_query_ctrl_r_runs(corpus_dir: Path) -> None:
    """The `ctrl+r` binding runs the current query."""

    async def scenario() -> None:
        app = LairsApp(data_path=str(corpus_dir))
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause()
            app.query_one(TabbedContent).active = "query"
            await pilot.pause()
            app.query_one("#editor", TextArea).text = "SELECT id FROM expressions"
            app.query_one("#editor", TextArea).focus()
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert app.query_one("#qresults", DataTable).row_count == 3

    asyncio.run(scenario())
