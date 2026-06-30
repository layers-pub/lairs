"""The Settings screen: review sources and manage muted datasets.

A modal overlay that lists the configured discovery sources (read-only) and the
permanently muted datasets, with the ability to unmute a dataset so a later crawl
or auto-index can pick it up again. Unmuting writes through the app's shared
:class:`~lairs.discovery.index.DiscoveryIndex`, so the next crawl re-discovers the
dataset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from lairs.discovery import load_sources

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from lairs.discovery.index import DiscoveryIndex

__all__ = ["SettingsScreen"]


class SettingsScreen(ModalScreen[None]):
    """A modal for reviewing sources and unmuting muted datasets.

    Parameters
    ----------
    index : lairs.discovery.index.DiscoveryIndex or None
        The shared discovery index, or ``None`` when no index is loaded.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("u", "unmute", "Unmute"),
        Binding("space", "unmute", "Unmute"),
    ]

    def __init__(self, index: DiscoveryIndex | None) -> None:
        super().__init__()
        self._index = index
        self._muted_uris: list[str] = []

    def compose(self) -> ComposeResult:
        """Compose the sources table and the muted-datasets table."""
        box = Vertical(
            Static("Sources", classes="settings-head"),
            DataTable(id="settings-sources", cursor_type="row"),
            Static("Muted datasets", classes="settings-head"),
            DataTable(id="settings-muted", cursor_type="row", zebra_stripes=True),
            Static("", id="settings-status"),
            id="settings-box",
        )
        box.border_title = "settings  (u: unmute, esc: close)"
        yield box

    def on_mount(self) -> None:
        """Populate the sources table and load the muted datasets."""
        sources = self.query_one("#settings-sources", DataTable)
        sources.add_columns("name", "endpoint", "kind", "enabled")
        for source in load_sources():
            sources.add_row(
                Text(source.name),
                Text(source.endpoint),
                Text(source.kind),
                Text("yes" if source.enabled else "no"),
            )
        self.query_one("#settings-muted", DataTable).add_columns(
            "name",
            "source",
            "muted at",
        )
        self._load_muted()

    def action_unmute(self) -> None:
        """Unmute the highlighted muted dataset and refresh the list."""
        if self._index is None:
            return
        row = self.query_one("#settings-muted", DataTable).cursor_row
        if not 0 <= row < len(self._muted_uris):
            return
        if self._index.unmute(self._muted_uris[row]):
            self._index.commit("unmute")
            self._load_muted()

    def _load_muted(self) -> None:
        """Reload the muted-datasets table from the index."""
        table = self.query_one("#settings-muted", DataTable)
        table.clear()
        self._muted_uris = []
        if self._index is None:
            self._set_status("No index loaded.")
            return
        records = self._index.muted()
        for record in records:
            self._muted_uris.append(record.uri)
            table.add_row(
                Text(record.name),
                Text(record.source_endpoint),
                Text(record.muted_at.date().isoformat()),
            )
        self._set_status(f"{len(records)} muted")

    def _set_status(self, message: str) -> None:
        """Update the status line."""
        self.query_one("#settings-status", Static).update(message)
