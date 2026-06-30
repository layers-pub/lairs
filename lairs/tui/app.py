"""The Textual application shell for the lairs explorer.

A tabbed, colorful TUI with an Explore tab (discovery index browser), a Browse
tab (a type-aware record explorer over a local Repository), and a Query tab
(SQL / concordance / CQL workbench). The shell owns global keybindings, the
theme cycle, and the help modal; the tabs own their own behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import httpx
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Markdown, TabbedContent, TabPane

from lairs.atproto.pds import PdsClient
from lairs.discovery import DiscoveryIndex, discover, load_sources
from lairs.tui.screens import (
    BrowsePane,
    DiscoverPane,
    ExplorePane,
    QueryPane,
    SettingsScreen,
)

if TYPE_CHECKING:
    from lairs.discovery.cards import DatasetCard

__all__ = ["LairsApp"]

# colorful themes cycled with Ctrl+T, starting from the first.
_THEMES: tuple[str, ...] = (
    "tokyo-night",
    "catppuccin-mocha",
    "nord",
    "gruvbox",
    "dracula",
    "monokai",
    "flexoki",
)

_HELP = """\
# lairs explorer

A colorful workbench for discovering and querying Layers corpus data.

## Tabs

- **Explore** (`1`): browse the discovery index. Type in the facet boxes to
  filter and re-rank live; the highlighted dataset's card shows on the right.
- **Browse** (`2`): explore every record in a local repository. The left tree
  lists the record types present (corpora, ontologies, experiments, resource
  collections, relation graphs, media, and the rest); pick one to list its
  records and filter them. The detail panel shows one focused view of the
  highlighted record at a time; press `v` to flip between the views that fit it,
  for example an annotated sentence's **Text**, a CoNLL-U **Grid**, a dependency
  **Tree**, an item's judgment distribution, an alignment's **Bitext**, or the
  full **Detail**.
- **Query** (`3`): run powerful searches over materialized data. Pick a
  mode, write a query, and press **Run** (`ctrl+r`). Click a schema node to
  insert its name.
- **Discover** (`4`): browse the configured sources and pick datasets to index.
  Pick a source on the left to crawl it; each dataset shows its state (`indexed`,
  `new`, or `muted`). Press `enter` or `space` to index a new dataset (it then
  appears in Explore) or to permanently mute an indexed one. Press `r` to
  re-crawl. Open **Settings** (`ctrl+s`) to review sources and unmute datasets.

## Query modes

- **SQL**: full DuckDB SQL over the materialized views (`expressions`,
  `annotations`, ...). Joins, aggregations, window functions, regex, and more.
  ```sql
  SELECT label, count(*) AS n FROM annotations GROUP BY label ORDER BY n DESC
  ```
- **Concordance**: a keyword-in-context (KWIC) search. The query is a regular
  expression matched against `expressions.text`; each hit shows left / match /
  right context.
  ```
  \\brun(s|ning)?\\b
  ```
- **CQL**: a corpus query language over token-aligned annotations. A query is a
  sequence of bracketed token constraints joined on adjacent token positions;
  each block matches exactly one token (repetition quantifiers are not
  supported). `=` exact, `!=` negated, `~` regular expression; `[]` matches any
  token.
  ```
  [label="DET"] [label="ADJ"] [label="NOUN"]
  ```

## Keys

| key | action |
| --- | --- |
| `1` / `2` / `3` / `4` | switch to Explore / Browse / Query / Discover |
| `v` | flip between views of the highlighted record (Browse) |
| `enter` / `space` | index or mute the highlighted dataset (Discover) |
| `r` | re-crawl the highlighted source (Discover) |
| `ctrl+r` | run the current query |
| `ctrl+s` | open settings (sources and muted datasets) |
| `ctrl+t` | cycle the color theme |
| `ctrl+p` | command palette |
| `f1` / `?` | this help |
| `ctrl+q` | quit |
"""


class HelpScreen(ModalScreen[None]):
    """A modal help overlay describing the tabs, query modes, and keys."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the scrollable help box."""
        box = VerticalScroll(Markdown(_HELP), id="help-box")
        box.border_title = "help  (esc to close)"
        yield box


class LairsApp(App[None]):
    """The lairs explorer application.

    Parameters
    ----------
    index_path : str or None, optional
        A discovery index directory to open on the Explore and Discover tabs. The
        index is created when the directory does not yet exist.
    data_path : str or None, optional
        A materialized Parquet directory to open on the Query tab.
    repo_path : str or None, optional
        A local Repository directory to open on the Browse tab.
    auto_index : bool, optional
        When ``True`` and an index is loaded, crawl the enabled sources on launch
        and index every newly discovered dataset that is not muted.
    """

    CSS_PATH = "styles.tcss"
    TITLE = "lairs"
    SUB_TITLE = "Layers data explorer"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f1", "help", "Help"),
        Binding("question_mark", "help", "Help", show=False),
        Binding("1", "show_tab('explore')", "Explore"),
        Binding("2", "show_tab('browse')", "Browse"),
        Binding("3", "show_tab('query')", "Query"),
        Binding("4", "show_tab('discover')", "Discover"),
        Binding("ctrl+s", "settings", "Settings"),
        Binding("ctrl+t", "cycle_theme", "Theme"),
    ]

    def __init__(
        self,
        *,
        index_path: str | None = None,
        data_path: str | None = None,
        repo_path: str | None = None,
        auto_index: bool = False,
    ) -> None:
        super().__init__()
        self._index_path = index_path
        self._data_path = data_path
        self._repo_path = repo_path
        self._auto_index = auto_index
        self._theme_index = 0
        self._index: DiscoveryIndex | None = (
            DiscoveryIndex.init(Path(index_path)) if index_path is not None else None
        )

    def _initial_tab(self) -> str:
        """Pick the opening tab from whichever data source was provided.

        A repository opens on Browse, a bare materialized directory on Query,
        and otherwise the Explore index is the front door.
        """
        if self._repo_path is not None:
            return "browse"
        if self._data_path is not None and self._index_path is None:
            return "query"
        return "explore"

    def compose(self) -> ComposeResult:
        """Compose the header, the Explore/Browse/Query tabs, and the footer."""
        yield Header(show_clock=True)
        with TabbedContent(initial=self._initial_tab()):
            with TabPane("Explore", id="explore"):
                yield ExplorePane(self._index_path)
            with TabPane("Browse", id="browse"):
                yield BrowsePane(self._repo_path)
            with TabPane("Query", id="query"):
                yield QueryPane(self._data_path)
            with TabPane("Discover", id="discover"):
                yield DiscoverPane(self._index)
        yield Footer()

    def on_mount(self) -> None:
        """Apply the starting theme and auto-index the sources when requested."""
        self.theme = _THEMES[0]
        if self._auto_index and self._index is not None:
            self._run_auto_index()

    def action_show_tab(self, tab: str) -> None:
        """Switch to a tab by id.

        Parameters
        ----------
        tab : str
            The target tab pane id (``"explore"``, ``"browse"``, ``"query"``, or
            ``"discover"``).
        """
        self.query_one(TabbedContent).active = tab

    def action_settings(self) -> None:
        """Open the settings modal for sources and muted datasets."""
        self.push_screen(SettingsScreen(self._index))

    def on_tabbed_content_tab_activated(
        self,
        event: TabbedContent.TabActivated,  # noqa: ARG002 - Textual message handler
    ) -> None:
        """React to a tab becoming active.

        Activating Explore reloads its index from disk so writes from the
        Discover tab, the Settings modal, or the auto-index worker show without a
        restart. Activating Discover starts its first crawl, so a network read
        happens only on demand.
        """
        active = self.query_one(TabbedContent).active
        if active == "explore":
            self._reload_explore()
        elif active == "discover":
            self.query_one(DiscoverPane).activate()

    @work(thread=True, group="auto-index")
    def _run_auto_index(self) -> None:
        """Crawl every enabled source and index new datasets, in a thread.

        Only network reads happen here; discovered cards are handed to the UI
        thread, which owns all index writes, so there is never a concurrent
        writer.
        """
        if self._index is None:
            return
        for source in load_sources():
            if not source.enabled:
                continue
            try:
                with PdsClient(source.endpoint) as client:
                    dids = client.list_repos()
                    cards = list(
                        discover(
                            dids,
                            describe=client,
                            list_corpora=client,
                            endpoint=source.endpoint,
                        ),
                    )
            except httpx.HTTPError, OSError:
                continue
            self.call_from_thread(self._index_new_cards, cards)

    def _index_new_cards(self, cards: list[DatasetCard]) -> None:
        """Index every card that is neither already indexed nor muted."""
        if self._index is None:
            return
        added = 0
        for card in cards:
            uri = card.summary.uri
            if self._index.is_muted(uri) or self._index.get_card(uri) is not None:
                continue
            self._index.put_card(card)
            added += 1
        if added:
            self._index.commit("auto-index")
            self._reload_explore()
            self.notify(f"auto-indexed {added} dataset(s)", timeout=3)

    def _reload_explore(self) -> None:
        """Reload the Explore pane from the index on disk, when it is mounted."""
        try:
            pane = self.query_one(ExplorePane)
        except NoMatches:
            return
        pane.reload()

    def action_help(self) -> None:
        """Open the help modal."""
        self.push_screen(HelpScreen())

    def action_cycle_theme(self) -> None:
        """Cycle to the next colorful theme."""
        self._theme_index = (self._theme_index + 1) % len(_THEMES)
        self.theme = _THEMES[self._theme_index]
        self.notify(f"theme: {self.theme}", timeout=2)
