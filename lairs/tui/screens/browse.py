"""The Browse pane: a type-aware record explorer over a local Repository.

Three panels: a tree of the record types present (grouped by namespace, with
counts), a filterable table of the selected type's records (with
type-appropriate columns), and a detail panel that renders the highlighted
record with its type-aware view.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Input, Markdown, Tree

from lairs.tui.browse import BrowseError, RepoBrowser
from lairs.tui.registry import label_of, namespace_of
from lairs.tui.views import columns_for, record_views, summarize

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from lairs._types import JsonValue

__all__ = ["BrowsePane"]


class BrowsePane(Horizontal):
    """A repository record browser with a type tree, list, and detail view.

    Parameters
    ----------
    repo_path : str or None
        Filesystem path to a local Repository, or ``None`` to start empty with
        on-screen guidance.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("v", "cycle_view", "View"),
        Binding("V", "cycle_view(-1)", "View back", show=False),
    ]

    def __init__(self, repo_path: str | None) -> None:
        super().__init__(id="browse-pane")
        self._repo_path = repo_path
        self._browser: RepoBrowser | None = None
        self._error: str | None = None
        self._nsid: str | None = None
        self._records: list[tuple[str, Mapping[str, JsonValue]]] = []
        self._rows: list[tuple[str, Mapping[str, JsonValue]]] = []
        self._views: list[tuple[str, Callable[[], str]]] = []
        self._mode = 0

    def compose(self):  # noqa: ANN201 - Textual compose generator
        """Compose the type tree, records table, and detail panel."""
        types = VerticalScroll(Tree("types", id="types"), id="types-wrap")
        types.border_title = "record types"
        yield types
        with Vertical(id="records-col"):
            yield Input(placeholder="filter records", id="rfilter")
            table = DataTable(id="records", zebra_stripes=True, cursor_type="row")
            table.border_title = "records"
            yield table
        detail = VerticalScroll(Markdown(id="rdetail"), id="rdetail-wrap")
        detail.border_title = "record"
        yield detail

    def on_mount(self) -> None:
        """Open the repository and build the type tree."""
        self._load_repo()
        self._build_type_tree()
        if self._error is not None:
            self.query_one("#rdetail", Markdown).update(self._error)

    def _load_repo(self) -> None:
        """Open the configured repository, recording any error."""
        if self._repo_path is None:
            self._error = (
                "No repository loaded. The Browse tab reads a local Repository of "
                "records. Populate one with "
                "`lairs pull <did> --endpoint <pds> --into <repo>`, then open it "
                "with `lairs tui --repo <repo>`."
            )
            return
        try:
            self._browser = RepoBrowser.open(Path(self._repo_path))
        except BrowseError as error:
            self._error = str(error)

    def _build_type_tree(self) -> None:
        """Populate the type tree with namespaces and record types."""
        tree = self.query_one("#types", Tree)
        tree.root.expand()
        if self._browser is None:
            tree.root.add_leaf("(no repository)")
            return
        grouped: dict[str, list[tuple[str, int]]] = {}
        for nsid, count in self._browser.type_counts():
            grouped.setdefault(namespace_of(nsid), []).append((nsid, count))
        for namespace, types in grouped.items():
            ns_node = tree.root.add(f"[b]{namespace}[/b]", expand=True)
            for nsid, count in types:
                ns_node.add_leaf(f"{label_of(nsid)} ({count})", data=nsid)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Load the records of the selected type into the records table."""
        data = event.node.data
        if isinstance(data, str):
            self._select_type(data)

    def _select_type(self, nsid: str) -> None:
        """Switch the records table to a record type and show its records."""
        if self._browser is None:
            return
        self._nsid = nsid
        self._records = self._browser.records_raw(nsid)
        table = self.query_one("#records", DataTable)
        table.clear(columns=True)
        table.add_columns(*columns_for(nsid))
        self.query_one("#rfilter", Input).value = ""
        self._apply_filter()
        table.focus()

    def _apply_filter(self) -> None:
        """Repopulate the records table, honoring the filter box."""
        if self._nsid is None:
            return
        table = self.query_one("#records", DataTable)
        table.clear()
        needle = self.query_one("#rfilter", Input).value.strip().lower()
        self._rows = []
        for uri, raw in self._records:
            cells = summarize(self._nsid, uri, raw)
            if needle and needle not in " ".join(cells).lower():
                continue
            self._rows.append((uri, raw))
            table.add_row(*(Text(cell) for cell in cells))
        if self._rows:
            self._show(0)
        else:
            self.query_one("#rdetail", Markdown).update("*No records.*")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Re-filter the records table as the filter box changes."""
        if event.input.id == "rfilter":
            self._apply_filter()

    def on_data_table_row_highlighted(
        self,
        event: DataTable.RowHighlighted,
    ) -> None:
        """Render the highlighted record in the detail panel."""
        self._show(event.cursor_row)

    def _show(self, index: int) -> None:
        """Load the highlighted record's views and render the first one."""
        if self._browser is None or self._nsid is None:
            return
        if 0 <= index < len(self._rows):
            uri, raw = self._rows[index]
            self._views = record_views(self._browser, self._nsid, uri, raw)
            self._mode = 0
            self._render_current()

    def _render_current(self) -> None:
        """Render the currently selected view into the detail panel."""
        detail = self.query_one("#rdetail", Markdown)
        wrap = self.query_one("#rdetail-wrap", VerticalScroll)
        if not self._views:
            detail.update("*No record.*")
            wrap.border_title = "record"
            return
        label, render = self._views[self._mode]
        position = f"{self._mode + 1}/{len(self._views)}"
        hint = "  ·  v: switch view" if len(self._views) > 1 else ""
        wrap.border_title = f"{label}  ·  {position}{hint}"
        detail.update(self._safe_render(label, render))
        wrap.scroll_home(animate=False)

    def _safe_render(self, label: str, render: Callable[[], str]) -> str:
        """Render a view, degrading to an error note instead of crashing the tab.

        The visualizers degrade gracefully on the malformed inputs probed in
        testing, but a renderer that raises over an unanticipated record shape
        would otherwise propagate out of the highlight handler and crash the
        Browse tab. The error is shown in the detail panel instead.
        """
        try:
            return render()
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            return f"*Could not render the {label} view:*\n\n```\n{error}\n```"

    def action_cycle_view(self, step: int = 1) -> None:
        """Flip to the next (or previous) view of the current record."""
        if len(self._views) > 1:
            self._mode = (self._mode + step) % len(self._views)
            self._render_current()
