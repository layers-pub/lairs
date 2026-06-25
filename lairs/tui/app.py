"""The Textual application shell for the lairs explorer.

A tabbed, colorful TUI with an Explore tab (discovery index browser), a Browse
tab (a type-aware record explorer over a local Repository), and a Query tab
(SQL / concordance / CQL workbench). The shell owns global keybindings, the
theme cycle, and the help modal; the tabs own their own behavior.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Markdown, TabbedContent, TabPane

from lairs.tui.screens import BrowsePane, ExplorePane, QueryPane

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
| `1` / `2` / `3` | switch to Explore / Browse / Query |
| `v` | flip between views of the highlighted record (Browse) |
| `ctrl+r` | run the current query |
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
        A discovery index directory to open on the Explore tab.
    data_path : str or None, optional
        A materialized Parquet directory to open on the Query tab.
    repo_path : str or None, optional
        A local Repository directory to open on the Browse tab.
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
        Binding("ctrl+t", "cycle_theme", "Theme"),
    ]

    def __init__(
        self,
        *,
        index_path: str | None = None,
        data_path: str | None = None,
        repo_path: str | None = None,
    ) -> None:
        super().__init__()
        self._index_path = index_path
        self._data_path = data_path
        self._repo_path = repo_path
        self._theme_index = 0

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
        yield Footer()

    def on_mount(self) -> None:
        """Apply the starting color theme."""
        self.theme = _THEMES[0]

    def action_show_tab(self, tab: str) -> None:
        """Switch to a tab by id.

        Parameters
        ----------
        tab : str
            The target tab pane id (``"explore"``, ``"browse"``, or
            ``"query"``).
        """
        self.query_one(TabbedContent).active = tab

    def action_help(self) -> None:
        """Open the help modal."""
        self.push_screen(HelpScreen())

    def action_cycle_theme(self) -> None:
        """Cycle to the next colorful theme."""
        self._theme_index = (self._theme_index + 1) % len(_THEMES)
        self.theme = _THEMES[self._theme_index]
        self.notify(f"theme: {self.theme}", timeout=2)
