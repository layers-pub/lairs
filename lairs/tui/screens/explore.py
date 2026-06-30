"""The Explore pane: browse and filter the discovery index.

Loads a :class:`lairs.discovery.index.DiscoveryIndex`, renders every dataset as
a row in a live-filtered table, and shows the highlighted dataset's full card in
a detail panel. The facet inputs map onto a
:class:`lairs.discovery.query.SearchQuery` and re-rank on every keystroke.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Input, Markdown

from lairs.discovery.index import DiscoveryIndex
from lairs.discovery.query import SearchQuery, search

if TYPE_CHECKING:
    from lairs.discovery.cards import DatasetCard

__all__ = ["ExplorePane"]

_COLUMNS: tuple[str, ...] = ("Name", "Domain", "Lang", "License", "#Expr", "Score")


def _int_or_none(value: str) -> int | None:
    """Parse a possibly-empty numeric field into an int, or ``None``."""
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _none_if_blank(value: str) -> str | None:
    """Return the stripped value, or ``None`` when it is blank."""
    text = value.strip()
    return text or None


class ExplorePane(Horizontal):
    """A discovery-index browser with facet filters and a detail card.

    Parameters
    ----------
    index_path : str or None
        Filesystem path to a discovery index directory, or ``None`` to start
        empty with on-screen guidance.
    """

    def __init__(self, index_path: str | None) -> None:
        super().__init__(id="explore-pane")
        self._index_path = index_path
        self._index: DiscoveryIndex | None = None
        self._cards: list[DatasetCard] = []
        self._hits: list[DatasetCard] = []
        self._error: str | None = None

    def compose(self):  # noqa: ANN201 - Textual compose generator
        """Compose the filter bar, results table, and detail panel."""
        with VerticalScroll(id="explore-left"):
            with Horizontal(classes="filterbar"):
                yield Input(placeholder="search name or description", id="f_text")
                yield Input(placeholder="domain", id="f_domain")
                yield Input(placeholder="language", id="f_lang")
                yield Input(placeholder="license", id="f_license")
                yield Input(placeholder="min #expr", id="f_min")
            with Horizontal(id="explore-body"):
                table = DataTable(id="results", zebra_stripes=True, cursor_type="row")
                table.border_title = "datasets"
                yield table
                detail = VerticalScroll(Markdown(id="detail"), id="detail-wrap")
                detail.border_title = "details"
                yield detail

    def on_mount(self) -> None:
        """Populate the table header, load the index, and run the first filter."""
        table = self.query_one("#results", DataTable)
        table.add_columns(*_COLUMNS)
        self._load_index()
        self._refilter()

    def reload(self) -> None:
        """Re-open the index from disk and re-run the current filter.

        Discovery writes (auto-index, the Discover tab, or unmuting) commit
        through the app's index handle; re-opening picks up those commits so the
        results reflect freshly indexed datasets without restarting the app.
        """
        self._index = None
        self._cards = []
        self._error = None
        self._load_index()
        self._refilter()

    def _load_index(self) -> None:
        """Open the configured index and cache its cards, recording any error."""
        if self._index_path is None:
            self._error = (
                "No discovery index loaded.\n\n"
                "Build one with `lairs index build --into <dir> --endpoint <relay>`, "
                "then open it with `lairs tui --index <dir>`."
            )
            return
        try:
            self._index = DiscoveryIndex.open(Path(self._index_path))
            self._cards = self._index.cards()
        except (OSError, ValueError) as error:  # pragma: no cover - defensive
            self._error = f"Could not open index at {self._index_path}:\n\n{error}"

    def _query(self) -> SearchQuery:
        """Build a :class:`SearchQuery` from the current facet inputs."""
        return SearchQuery(
            text=_none_if_blank(self.query_one("#f_text", Input).value),
            domain=_none_if_blank(self.query_one("#f_domain", Input).value),
            language=_none_if_blank(self.query_one("#f_lang", Input).value),
            license=_none_if_blank(self.query_one("#f_license", Input).value),
            min_expressions=_int_or_none(self.query_one("#f_min", Input).value),
        )

    def _refilter(self) -> None:
        """Re-rank the cards against the current query and repaint the table."""
        table = self.query_one("#results", DataTable)
        table.clear()
        if self._error is not None:
            self._hits = []
            self.query_one("#detail", Markdown).update(self._error)
            return
        hits = search(self._cards, self._query())
        self._hits = [hit.card for hit in hits]
        for hit in hits:
            summary = hit.card.summary
            table.add_row(
                Text(summary.name),
                Text(summary.domain or "-"),
                Text(_languages(hit.card)),
                Text(summary.license or "-"),
                Text(
                    str(summary.expression_count) if summary.expression_count else "-"
                ),
                Text(f"{hit.score:.1f}"),
            )
        if self._hits:
            self._show_card(self._hits[0])
        else:
            self.query_one("#detail", Markdown).update(
                f"No datasets match.\n\n*{len(self._cards)} indexed.*"
            )

    def _show_card(self, card: DatasetCard) -> None:
        """Render a dataset card into the detail panel as Markdown."""
        self.query_one("#detail", Markdown).update(_card_markdown(card))

    def on_input_changed(self, event: Input.Changed) -> None:  # noqa: ARG002
        """Re-filter whenever any facet input changes."""
        self._refilter()

    def on_data_table_row_highlighted(
        self,
        event: DataTable.RowHighlighted,
    ) -> None:
        """Show the highlighted dataset's card in the detail panel."""
        if 0 <= event.cursor_row < len(self._hits):
            self._show_card(self._hits[event.cursor_row])


def _languages(card: DatasetCard) -> str:
    """Return a compact language label for a card row."""
    summary = card.summary
    if summary.languages:
        return ", ".join(summary.languages[:3])
    return summary.language or "-"


def _card_markdown(card: DatasetCard) -> str:
    """Render a dataset card to a Markdown detail view."""
    summary = card.summary
    lines: list[str] = [f"# {summary.name}", ""]
    if summary.description:
        lines += [summary.description, ""]
    lines.append("| field | value |")
    lines.append("| --- | --- |")
    rows: list[tuple[str, str | None]] = [
        ("domain", summary.domain),
        ("languages", ", ".join(summary.languages) or summary.language),
        ("license", summary.license),
        ("version", summary.version),
        ("expressions", _maybe_int(summary.expression_count)),
        ("adjudication", "yes" if summary.has_adjudication else "no"),
        ("annotation rounds", _maybe_int(card.annotation_rounds)),
        ("adjudication method", card.adjudication_method),
        ("quality metrics", ", ".join(card.quality_metrics) or None),
        ("handle", summary.handle),
        ("source", summary.source_endpoint),
        ("created", summary.created_at),
    ]
    for label, value in rows:
        if value:
            lines.append(f"| {label} | {value} |")
    if summary.ontology_refs:
        lines += ["", "**ontologies**", ""]
        lines += [f"- `{ref}`" for ref in summary.ontology_refs]
    if summary.eprint_refs:
        lines += ["", "**eprints**", ""]
        lines += [f"- `{ref}`" for ref in summary.eprint_refs]
    lines += ["", f"`{summary.uri}`"]
    return "\n".join(lines)


def _maybe_int(value: int | None) -> str | None:
    """Render an optional integer as a string, or ``None`` when unset."""
    return str(value) if value is not None else None
