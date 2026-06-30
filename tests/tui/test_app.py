"""Pilot-driven tests for the lairs explorer app.

Textual's ``App.run_test`` is async; each test drives it through ``asyncio.run``
so the suite needs no async-pytest plugin.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

import httpx
import pytest
from textual.widgets import (
    DataTable,
    Input,
    RadioButton,
    RadioSet,
    Static,
    TabbedContent,
    TextArea,
    Tree,
)

from lairs.atproto.pds import RecordEnvelope, RepoDescription
from lairs.discovery import DiscoveryIndex, Source
from lairs.discovery.cards import CardFreshness, CardProvenance, DatasetCard
from lairs.discovery.models import DatasetSummary
from lairs.tui.app import HelpScreen, LairsApp
from lairs.tui.query import QueryError
from lairs.tui.screens.discover import DiscoverPane
from lairs.tui.screens.explore import (
    ExplorePane,
    _card_markdown,
    _int_or_none,
    _languages,
    _none_if_blank,
)
from lairs.tui.screens.query import QueryPane
from lairs.tui.screens.settings import SettingsScreen

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Protocol

    from lairs._types import JsonValue

    class _PdsLike(Protocol):
        """The live-PDS connection attributes the integration tests read."""

        endpoint: str
        did: str
        access_jwt: str


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
    app.query_one("#mode", RadioSet).query(RadioButton)[mode].value = True


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


# ---- discover tab ---------------------------------------------------------

_DISCOVER_NSID = "pub.layers.corpus.corpus"


def _discover_value(name: str, domain: str) -> JsonValue:
    """Build a minimal corpus record value for the fake PDS."""
    return {
        "$type": _DISCOVER_NSID,
        "name": name,
        "createdAt": "2026-06-18T00:00:00Z",
        "domain": domain,
    }


_DISCOVER_ENVELOPES = (
    RecordEnvelope(
        uri="at://did:plc:disc/pub.layers.corpus.corpus/a",
        cid="bafa",
        value=_discover_value("Discovered Alpha", "legal"),
    ),
    RecordEnvelope(
        uri="at://did:plc:disc/pub.layers.corpus.corpus/b",
        cid="bafb",
        value=_discover_value("Discovered Beta", "biomedical"),
    ),
)


class _FakeDiscoverClient:
    """A context-managed PdsClient stand-in that serves two corpora."""

    def __init__(self, endpoint: str | None) -> None:
        self.endpoint = endpoint

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def list_repos(self) -> list[str]:
        return ["did:plc:disc"]

    def describe_repo(self, repo: str) -> RepoDescription:
        return RepoDescription(
            did=repo,
            handle="disc.test",
            collections=(_DISCOVER_NSID,),
        )

    def list_records(self, repo: str, collection: str) -> Iterator[RecordEnvelope]:
        _ = (repo, collection)
        yield from _DISCOVER_ENVELOPES


class _FailingDiscoverClient:
    """A PdsClient stand-in whose crawl fails, to exercise error handling."""

    def __init__(self, endpoint: str | None) -> None:
        self.endpoint = endpoint

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def list_repos(self) -> list[str]:
        msg = "connection refused"
        raise httpx.ConnectError(msg)


def _fake_source() -> Source:
    """Build a single enabled source for the faked-client auto-index tests."""
    return Source(
        name="fake",
        endpoint="https://pds.example",
        kind="pds",
        enabled=True,
        builtin=False,
    )


def test_discover_does_not_crawl_at_boot(index_path: str) -> None:
    """The Discover pane mounts without a network read until it is opened."""

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            pane = app.query_one(DiscoverPane)
            assert pane._crawled is False
            assert len(pane._sources) >= 1

    asyncio.run(scenario())


def test_discover_tab_lists_new_datasets(
    index_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("lairs.tui.screens.discover.PdsClient", _FakeDiscoverClient)

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#discovered", DataTable).row_count == 2
            pane = app.query_one(DiscoverPane)
            assert pane._crawled is True
            assert all(pane._state_of(card) == "new" for card in pane._cards)

    asyncio.run(scenario())


def test_discover_toggle_indexes_into_explore(
    index_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("lairs.tui.screens.discover.PdsClient", _FakeDiscoverClient)

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            pane = app.query_one(DiscoverPane)
            pane._toggle(0)
            await pilot.pause()
            card = pane._cards[0]
            assert pane._state_of(card) == "indexed"
            assert app._index is not None
            assert app._index.get_card(card.summary.uri) is not None
            # the newly indexed dataset appears in Explore once its tab reloads.
            await pilot.press("1")
            await pilot.pause()
            assert app.query_one("#results", DataTable).row_count == 4

    asyncio.run(scenario())


def test_discover_toggle_mutes_indexed(
    index_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("lairs.tui.screens.discover.PdsClient", _FakeDiscoverClient)

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            pane = app.query_one(DiscoverPane)
            card = pane._cards[0]
            pane._toggle(0)  # new -> indexed
            assert pane._state_of(card) == "indexed"
            pane._toggle(0)  # indexed -> muted
            assert pane._state_of(card) == "muted"
            assert app._index is not None
            assert app._index.is_muted(card.summary.uri) is True

    asyncio.run(scenario())


def test_settings_modal_unmutes(
    index_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("lairs.tui.screens.discover.PdsClient", _FakeDiscoverClient)

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            pane = app.query_one(DiscoverPane)
            card = pane._cards[0]
            pane._toggle(0)  # index
            pane._toggle(0)  # mute
            muted_uri = card.summary.uri
            await pilot.press("ctrl+s")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            muted_table = screen.query_one("#settings-muted", DataTable)
            assert muted_table.row_count == 1
            screen.action_unmute()
            await pilot.pause()
            assert muted_table.row_count == 0
            assert app._index is not None
            assert app._index.is_muted(muted_uri) is False

    asyncio.run(scenario())


def test_auto_index_populates_explore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("lairs.tui.app.PdsClient", _FakeDiscoverClient)

    async def scenario() -> None:
        app = LairsApp(index_path=str(tmp_path / "auto"), auto_index=True)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._index is not None
            assert len(app._index.cards()) == 2
            # explore is the initial tab and reloads after the auto-index commit.
            assert app.query_one("#results", DataTable).row_count == 2

    asyncio.run(scenario())


def test_auto_index_respects_a_mute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a permanently muted dataset must not be re-indexed by the launch auto-index;
    # the other discovered dataset still is. this is the core mute guarantee.
    monkeypatch.setattr("lairs.tui.app.PdsClient", _FakeDiscoverClient)
    monkeypatch.setattr("lairs.tui.app.load_sources", lambda: [_fake_source()])
    muted_uri = _DISCOVER_ENVELOPES[0].uri
    other_uri = _DISCOVER_ENVELOPES[1].uri
    idx_dir = tmp_path / "idx"
    seed = DiscoveryIndex.init(idx_dir)
    seed.mute(
        DatasetCard(
            summary=DatasetSummary(uri=muted_uri, did="did:plc:disc", name="muted"),
            provenance=CardProvenance(
                source_did="did:plc:disc",
                source_endpoint="https://pds.example",
                discovered_via="crawl",
            ),
            freshness=CardFreshness(first_seen_at=_NOW, last_updated_at=_NOW),
        ),
    )
    seed.commit("pre-mute")

    async def scenario() -> None:
        app = LairsApp(index_path=str(idx_dir), auto_index=True)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._index is not None
            assert app._index.is_muted(muted_uri) is True
            assert app._index.get_card(muted_uri) is None
            assert app._index.get_card(other_uri) is not None

    asyncio.run(scenario())


def test_auto_index_survives_unreachable_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a source that cannot be reached is skipped, not fatal: the app boots, the
    # index stays empty, and Explore shows nothing.
    monkeypatch.setattr("lairs.tui.app.PdsClient", _FailingDiscoverClient)
    monkeypatch.setattr("lairs.tui.app.load_sources", lambda: [_fake_source()])

    async def scenario() -> None:
        app = LairsApp(index_path=str(tmp_path / "idx"), auto_index=True)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._index is not None
            assert app._index.cards() == []
            assert app.query_one("#results", DataTable).row_count == 0

    asyncio.run(scenario())


def test_discover_crawl_failure_shows_status(
    index_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a failed crawl reports a status and leaves the table empty, never crashing.
    monkeypatch.setattr(
        "lairs.tui.screens.discover.PdsClient",
        _FailingDiscoverClient,
    )

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            status = str(app.query_one("#discover-status", Static).render())
            assert "crawl failed" in status
            assert app.query_one("#discovered", DataTable).row_count == 0

    asyncio.run(scenario())


def test_discover_toggle_unmutes_back_to_indexed(
    index_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # toggling cycles new -> indexed -> muted -> indexed, so a mute made by hand
    # can be undone from the same tab.
    monkeypatch.setattr("lairs.tui.screens.discover.PdsClient", _FakeDiscoverClient)

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            pane = app.query_one(DiscoverPane)
            card = pane._cards[0]
            pane._toggle(0)  # new -> indexed
            pane._toggle(0)  # indexed -> muted
            assert pane._state_of(card) == "muted"
            pane._toggle(0)  # muted -> indexed
            assert pane._state_of(card) == "indexed"
            assert app._index is not None
            assert app._index.is_muted(card.summary.uri) is False
            assert app._index.get_card(card.summary.uri) is not None

    asyncio.run(scenario())


def test_discover_keybindings_toggle_and_refresh(
    index_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the space and r bindings drive the pane: space indexes the highlighted
    # dataset, r re-crawls the highlighted source.
    monkeypatch.setattr("lairs.tui.screens.discover.PdsClient", _FakeDiscoverClient)

    async def scenario() -> None:
        app = LairsApp(index_path=index_path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            pane = app.query_one(DiscoverPane)
            app.query_one("#discovered", DataTable).focus()
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            assert pane._state_of(pane._cards[0]) == "indexed"
            await pilot.press("r")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#discovered", DataTable).row_count == 2

    asyncio.run(scenario())


# ---- discover / auto-index against a live PDS -----------------------------


def _fresh_account(server: _PdsLike) -> tuple[str, str]:
    """Create a new empty account on the PDS, returning (did, access_jwt)."""
    token = secrets.token_hex(6)
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.server.createAccount",
        json={
            "handle": f"tu{token}.test",
            "email": f"tu{token}@example.test",
            "password": secrets.token_hex(12),
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    return str(body["did"]), str(body["accessJwt"])


def _seed_corpus_on(server: _PdsLike, did: str, jwt: str, name: str) -> str:
    """Create a corpus on a specific account and return its AT-URI."""
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {jwt}"},
        json={
            "repo": did,
            "collection": _DISCOVER_NSID,
            "record": {
                "$type": _DISCOVER_NSID,
                "name": name,
                "createdAt": "2026-06-18T00:00:00Z",
            },
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return str(response.json()["uri"])


def _pds_source(server: _PdsLike) -> Source:
    """Build a configured source pointing at the live test PDS."""
    return Source(
        name="test-pds",
        endpoint=server.endpoint,
        kind="pds",
        enabled=True,
        builtin=False,
    )


@pytest.mark.integration
def test_auto_index_live_pulls_from_pds(
    pds_server: _PdsLike,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the real launch path: list the PDS's repos, crawl them, and index the
    # corpora found, all over a live PDS through a real PdsClient.
    did, jwt = _fresh_account(pds_server)
    token = secrets.token_hex(4)
    uri_a = _seed_corpus_on(pds_server, did, jwt, f"live-{token}-alpha")
    uri_b = _seed_corpus_on(pds_server, did, jwt, f"live-{token}-beta")
    monkeypatch.setattr("lairs.tui.app.load_sources", lambda: [_pds_source(pds_server)])

    async def scenario() -> None:
        app = LairsApp(index_path=str(tmp_path / "idx"), auto_index=True)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._index is not None
            assert app._index.get_card(uri_a) is not None
            assert app._index.get_card(uri_b) is not None
            # explore surfaces them; filter on the unique token to isolate from
            # any other repos on the shared session PDS.
            app.query_one("#f_text", Input).value = token
            await pilot.pause()
            assert app.query_one("#results", DataTable).row_count == 2

    asyncio.run(scenario())


@pytest.mark.integration
def test_discover_tab_live_indexes_from_pds(
    pds_server: _PdsLike,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the real Discover path: open the tab, crawl the live PDS, and toggle a
    # discovered corpus into the index.
    did, jwt = _fresh_account(pds_server)
    token = secrets.token_hex(4)
    uri = _seed_corpus_on(pds_server, did, jwt, f"disc-{token}")
    monkeypatch.setattr(
        "lairs.tui.screens.discover.load_sources",
        lambda: [_pds_source(pds_server)],
    )

    async def scenario() -> None:
        app = LairsApp(index_path=str(tmp_path / "idx"), auto_index=False)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            pane = app.query_one(DiscoverPane)
            row = next(
                (i for i, card in enumerate(pane._cards) if card.summary.uri == uri),
                None,
            )
            assert row is not None
            assert pane._state_of(pane._cards[row]) == "new"
            pane._toggle(row)
            assert pane._state_of(pane._cards[row]) == "indexed"
            assert app._index is not None
            assert app._index.get_card(uri) is not None

    asyncio.run(scenario())
