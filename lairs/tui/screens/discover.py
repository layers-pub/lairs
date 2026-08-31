"""The Discover pane: browse configured sources and pick datasets to index.

Lists the configured sources, crawls the selected source for datasets of every
type in a background worker, and shows each dataset with its type (``corpus`` or
a catalogue collection's kind) and index state: ``indexed`` (in the local index
and visible in Explore), ``new`` (discovered but not indexed), or ``muted``
(permanently excluded). Toggling a dataset indexes it or mutes it. The crawl
reuses :func:`lairs.discovery.discover` and
:func:`lairs.discovery.discover_collections` over a
:class:`~lairs.atproto.pds.PdsClient`, so it follows the same ``listRepos`` path
as ``lairs index build``.

The background worker only performs network reads; every index write happens on
the UI thread against the app's shared :class:`~lairs.discovery.index.DiscoveryIndex`,
so there is never a concurrent writer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

import httpx
from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Static

from lairs.atproto.pds import PdsClient
from lairs.discovery import discover, discover_collections, load_sources
from lairs.discovery.cards import CollectionCard, DatasetCard

if TYPE_CHECKING:
    from lairs.discovery.index import DiscoveryIndex
    from lairs.discovery.sources import Source

__all__ = ["DiscoverPane"]

type _Card = DatasetCard | CollectionCard

_DATASET_COLUMNS: tuple[str, ...] = ("state", "name", "type", "lang")


def _lang_label(card: _Card) -> str:
    """Return a compact language label for a dataset row."""
    languages = card.summary.languages
    if languages:
        return ", ".join(languages[:3])
    return "-"


def _type_label(card: _Card) -> str:
    """Return a dataset's type: ``corpus`` or the collection's own kind."""
    if isinstance(card, DatasetCard):
        return "corpus"
    return card.summary.kind or "collection"


class DiscoverPane(Horizontal):
    """Browse configured sources and select datasets to index or mute."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle_dataset", "Index/Mute"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, index: DiscoveryIndex | None) -> None:
        super().__init__(id="discover-pane")
        self._index = index
        self._sources: list[Source] = []
        self._cards: list[_Card] = []
        self._crawled = False

    @override
    def compose(self):  # noqa: ANN201 - Textual compose generator
        """Compose the sources list, the discovered-datasets table, and status."""
        with Vertical(id="discover-left"):
            sources = DataTable(id="sources", cursor_type="row")
            sources.border_title = "sources"
            yield sources
        with Vertical(id="discover-right"):
            datasets = DataTable(
                id="discovered",
                cursor_type="row",
                zebra_stripes=True,
            )
            datasets.border_title = "datasets  (enter/space: index or mute, r: refresh)"
            yield datasets
            yield Static("", id="discover-status")

    def on_mount(self) -> None:
        """Load the sources and populate the source list, without crawling.

        Crawling is deferred to :meth:`activate` so a network read happens only
        when the user opens the Discover tab, not when the app mounts.
        """
        self.query_one("#sources", DataTable).add_columns("source", "endpoint")
        self.query_one("#discovered", DataTable).add_columns(*_DATASET_COLUMNS)
        if self._index is None:
            self._set_status(
                "No index loaded. Launch with `lairs tui --index <dir>`.",
            )
            return
        self._sources = [source for source in load_sources() if source.enabled]
        table = self.query_one("#sources", DataTable)
        for source in self._sources:
            table.add_row(Text(source.name), Text(source.endpoint))
        self._set_status("select a source (enter) to crawl, or press r")

    def activate(self) -> None:
        """Crawl the first source the first time the tab is opened.

        Called by the app when the Discover tab is activated; a no-op once any
        crawl has started, so reopening the tab does not re-crawl.
        """
        if not self._crawled and self._sources:
            self._start_crawl(self._sources[0])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Crawl a selected source, or toggle a selected dataset's index state."""
        if event.data_table.id == "sources":
            if 0 <= event.cursor_row < len(self._sources):
                self._start_crawl(self._sources[event.cursor_row])
        elif event.data_table.id == "discovered":
            self._toggle(event.cursor_row)

    def action_toggle_dataset(self) -> None:
        """Toggle the highlighted dataset between indexed and muted."""
        self._toggle(self.query_one("#discovered", DataTable).cursor_row)

    def action_refresh(self) -> None:
        """Re-crawl the highlighted source."""
        row = self.query_one("#sources", DataTable).cursor_row
        if 0 <= row < len(self._sources):
            self._start_crawl(self._sources[row])

    def _start_crawl(self, source: Source) -> None:
        """Clear the dataset table and launch the crawl worker for a source."""
        self._crawled = True
        self._cards = []
        self.query_one("#discovered", DataTable).clear()
        self._set_status(f"crawling {source.name}...")
        self._crawl(source)

    @work(thread=True, exclusive=True, group="discover-crawl")
    def _crawl(self, source: Source) -> None:
        """Crawl a source for datasets in a background thread.

        Only network reads happen here; discovered cards are posted to the UI
        thread, which owns all index access.
        """
        try:
            with PdsClient(source.endpoint) as client:
                dids = list(client.list_repos())
                for card in discover(
                    dids,
                    describe=client,
                    list_corpora=client,
                    endpoint=source.endpoint,
                ):
                    self.app.call_from_thread(self._add_card, card)
                for collection_card in discover_collections(
                    dids,
                    describe=client,
                    list_collections=client,
                    endpoint=source.endpoint,
                ):
                    self.app.call_from_thread(self._add_card, collection_card)
        except (httpx.HTTPError, OSError) as error:
            self.app.call_from_thread(self._set_status, f"crawl failed: {error}")
            return
        self.app.call_from_thread(self._crawl_done)

    def _crawl_done(self) -> None:
        """Report the final dataset count once the crawl finishes."""
        self._set_status(f"{len(self._cards)} dataset(s)")

    def _add_card(self, card: _Card) -> None:
        """Append a discovered card and render its row with its index state."""
        self._cards.append(card)
        self.query_one("#discovered", DataTable).add_row(
            Text(self._state_of(card)),
            Text(card.summary.name),
            Text(_type_label(card)),
            Text(_lang_label(card)),
        )

    def _state_of(self, card: _Card) -> str:
        """Return the dataset's state: indexed, new, or muted."""
        if self._index is None:
            return "new"
        uri = card.summary.uri
        if self._index.is_muted(uri):
            return "muted"
        indexed = (
            self._index.get_collection_card(uri)
            if isinstance(card, CollectionCard)
            else self._index.get_card(uri)
        )
        if indexed is not None:
            return "indexed"
        return "new"

    def _toggle(self, row: int) -> None:
        """Index a new or muted dataset, or mute an indexed one."""
        if self._index is None or not (0 <= row < len(self._cards)):
            return
        card = self._cards[row]
        if self._state_of(card) == "indexed":
            self._index.mute(card)
        else:
            self._index.unmute(card.summary.uri)
            if isinstance(card, CollectionCard):
                self._index.put_collection_card(card)
            else:
                self._index.put_card(card)
        self._index.commit("discover toggle")
        table = self.query_one("#discovered", DataTable)
        table.update_cell_at(Coordinate(row, 0), Text(self._state_of(card)))

    def _set_status(self, message: str) -> None:
        """Update the status line."""
        self.query_one("#discover-status", Static).update(message)
