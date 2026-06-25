"""The Query pane: run SQL, KWIC concordance, and CQL over a corpus.

Opens a directory of materialized Parquet views as a :class:`QueryEngine`, shows
the schema in a browsable tree, and runs the editor's text through one of three
modes. Selecting a schema node inserts its name into the editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.markup import escape
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    RadioButton,
    RadioSet,
    Static,
    TextArea,
    Tree,
)

from lairs.tui.query import CqlError, QueryEngine, QueryError

if TYPE_CHECKING:
    from lairs.tui.query import QueryResult

__all__ = ["QueryPane"]

# the three query modes, by radio index.
_MODE_SQL = 0
_MODE_CONCORDANCE = 1
_MODE_CQL = 2

# the starter text shown for each mode the first time it is selected.
_STARTERS: dict[int, str] = {
    _MODE_SQL: "SELECT * FROM expressions LIMIT 50",
    _MODE_CONCORDANCE: r"\bthe\b",
    _MODE_CQL: '[label="DET"] [label="NOUN"]',
}

_MAX_DISPLAY_COLUMNS = 12
_MAX_CELL_WIDTH = 80


class QueryPane(Horizontal):
    """A three-mode query workbench over a materialized corpus.

    Parameters
    ----------
    data_path : str or None
        Filesystem path to a directory of materialized Parquet views, or
        ``None`` to start empty with on-screen guidance.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+r", "run", "Run query", priority=True),
    ]

    def __init__(self, data_path: str | None) -> None:
        super().__init__(id="query-pane")
        self._data_path = data_path
        self._engine: QueryEngine | None = None
        self._error: str | None = None
        self._seeded: set[int] = set()

    def compose(self):  # noqa: ANN201 - Textual compose generator
        """Compose the schema tree, mode bar, editor, actions, and results."""
        schema = VerticalScroll(Tree("schema", id="schema"), id="schema-wrap")
        schema.border_title = "schema"
        yield schema
        with Vertical(id="qmain"):
            with Horizontal(classes="modebar"), RadioSet(id="mode"):
                yield RadioButton("SQL", value=True)
                yield RadioButton("Concordance")
                yield RadioButton("CQL")
            yield TextArea.code_editor("", id="editor")
            with Horizontal(classes="qactions"):
                yield Button("Run \\[ctrl+r]", id="run", variant="success")
                yield Static("", id="qstatus")
            results = DataTable(id="qresults", zebra_stripes=True, cursor_type="cell")
            results.border_title = "results"
            yield results

    def on_mount(self) -> None:
        """Open the engine, build the schema tree, and seed the SQL starter."""
        self._load_engine()
        self._build_schema_tree()
        self._seed_mode(_MODE_SQL)
        if self._error is not None:
            self._set_status(self._error, error=True)

    def _load_engine(self) -> None:
        """Open the configured data directory, recording any error."""
        if self._data_path is None:
            self._error = (
                "No data loaded. The Query tab reads any directory of materialized "
                "Parquet views. Produce one with `Corpus.materialize` or "
                "`lairs materialize <corpus-uri> --endpoint <pds> --out <dir>`, then "
                "open it with `lairs tui --data <dir>`."
            )
            return
        try:
            self._engine = QueryEngine.open(Path(self._data_path))
        except QueryError as error:
            self._error = str(error)

    def _build_schema_tree(self) -> None:
        """Populate the schema tree with tables and their columns."""
        tree = self.query_one("#schema", Tree)
        tree.root.expand()
        if self._engine is None:
            tree.root.add_leaf("(no data)")
            return
        for table, columns in self._engine.schema():
            node = tree.root.add(f"[b]{table}[/b]", data=table, expand=True)
            for column in columns:
                node.add_leaf(column, data=column)

    def _seed_mode(self, mode: int) -> None:
        """Fill the editor with the starter for a mode the first time it is used."""
        if mode in self._seeded:
            return
        editor = self.query_one("#editor", TextArea)
        if not editor.text.strip():
            editor.text = self._starter(mode)
            editor.move_cursor(editor.document.end)
        self._seeded.add(mode)

    def _starter(self, mode: int) -> str:
        """Return the starter query for a mode.

        The SQL starter selects from the first materialized view so it is useful
        for any corpus or other produce, not just one that has an ``expressions``
        table.
        """
        if mode == _MODE_SQL and self._engine is not None and self._engine.tables:
            # the table name is an engine-sanitized identifier, not user input.
            return f"SELECT * FROM {self._engine.tables[0]} LIMIT 50"  # noqa: S608
        return _STARTERS.get(mode, "")

    def _mode(self) -> int:
        """Return the currently selected query mode index."""
        return self.query_one("#mode", RadioSet).pressed_index

    def _set_status(self, message: str, *, error: bool = False) -> None:
        """Write a one-line status message, colored for success or error.

        The message is markup-escaped so an error string or query fragment
        containing brackets cannot break or hijack the colour markup.
        """
        color = "$error" if error else "$success"
        self.query_one("#qstatus", Static).update(f"[{color}]{escape(message)}[/]")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Seed the starter query when the mode changes."""
        self._seed_mode(event.index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Run the query when the Run button is pressed."""
        if event.button.id == "run":
            self.action_run()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Insert a selected table or column name at the editor cursor.

        A separating space is added when the cursor does not already sit at a
        token boundary, so an identifier never fuses with the preceding text;
        the cursor follows the insertion.
        """
        data = event.node.data
        if not isinstance(data, str):
            return
        editor = self.query_one("#editor", TextArea)
        before = editor.get_text_range((0, 0), editor.cursor_location)
        prefix = "" if not before or before[-1] in " \n\t(.," else " "
        editor.insert(f"{prefix}{data} ")
        editor.focus()

    def action_run(self) -> None:
        """Execute the editor's text in the current mode and show the result."""
        if self._engine is None:
            self._set_status(self._error or "no corpus loaded", error=True)
            return
        text = self.query_one("#editor", TextArea).text.strip()
        if not text:
            self._set_status("nothing to run", error=True)
            return
        mode = self._mode()
        try:
            result = self._dispatch(mode, text)
        except (QueryError, CqlError) as error:
            self._set_status(str(error).replace("\n", " "), error=True)
            return
        self._paint_result(result)

    def _dispatch(self, mode: int, text: str) -> QueryResult:
        """Run ``text`` through the engine for the selected mode."""
        engine = self._engine
        assert engine is not None  # noqa: S101 - guarded by action_run
        if mode == _MODE_CONCORDANCE:
            return engine.concordance(text)
        if mode == _MODE_CQL:
            return engine.cql(text)
        return engine.run_sql(text)

    def _paint_result(self, result: QueryResult) -> None:
        """Paint a query result into the results table and the status line."""
        table = self.query_one("#qresults", DataTable)
        table.clear(columns=True)
        columns = result.columns[:_MAX_DISPLAY_COLUMNS]
        if columns:
            table.add_columns(*(Text(name) for name in columns))
        for row in result.rows:
            table.add_row(*(Text(_clip(cell)) for cell in row.cells[: len(columns)]))
        more = " (truncated)" if result.truncated else ""
        self._set_status(f"{result.row_count} rows{more} in {result.elapsed_ms:.0f} ms")


def _clip(value: str) -> str:
    """Clip a cell value to a sensible display width."""
    if len(value) > _MAX_CELL_WIDTH:
        return value[: _MAX_CELL_WIDTH - 1] + "…"
    return value
