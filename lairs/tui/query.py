"""The query engine behind the TUI: DuckDB SQL, KWIC concordance, and CQL.

A :class:`QueryEngine` opens a directory of materialized Parquet views (the
output of ``Corpus.materialize`` or ``lairs materialize``: ``expressions``,
``annotations``, and any per-collection tables) and registers each as a DuckDB
view. Three query surfaces run over those views:

* :meth:`QueryEngine.run_sql` runs arbitrary read-only DuckDB SQL, the full
  power layer (joins, aggregations, window functions, regex, full-text).
* :meth:`QueryEngine.concordance` runs a keyword-in-context (KWIC) search: a
  regular expression over a text column, returning left/match/right windows.
* :meth:`QueryEngine.cql` compiles a CQL token-pattern (corpus query language),
  e.g. ``[label="DET"] [label="NOUN"]``, into a self-join over the token-aligned
  annotations table, returning the matching token sequences.

The engine is pure Python and has no Textual dependency, so it is unit-testable
on its own. Every result is a typed :class:`QueryResult`.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import didactic.api as dx
import duckdb

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "CqlError",
    "QueryEngine",
    "QueryError",
    "QueryResult",
    "QueryRow",
]

# the conventional materialized view names, surfaced first in the UI.
_PREFERRED_TABLE_ORDER: tuple[str, ...] = (
    "expressions",
    "annotations",
    "segmentations",
    "edges",
    "media",
)

# columns the concordance prefers as the row label, in priority order.
_SOURCE_COLUMN_PREFERENCE: tuple[str, ...] = ("uri", "id", "layer_uri")

_DEFAULT_ROW_LIMIT = 500
_DEFAULT_KWIC_WINDOW = 48

_IDENT_RE = re.compile(r"[^0-9a-zA-Z_]")
_CQL_BLOCK_RE = re.compile(r"\[([^\]]*)\]")
_CQL_CONSTRAINT_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*(=|!=|~)\s*"([^"]*)"')
# a repetition quantifier directly following a token block; unsupported in 0.1.0.
_CQL_QUANTIFIER_RE = re.compile(r"\]\s*([*+?{])")
_WHITESPACE_RE = re.compile(r"\s+")

# a single scalar cell from a query result, rendered to a string for display.
type _Cell = str | int | float | bool | None


class QueryError(Exception):
    """Raised when a query fails to execute or compile."""


class CqlError(QueryError):
    """Raised when a CQL token-pattern fails to parse against the schema."""


class QueryRow(dx.Model):
    """One result row as a tuple of stringified cells.

    Attributes
    ----------
    cells : tuple of str
        The row's cell values, rendered to strings for display.
    """

    cells: tuple[str, ...] = dx.field(description="stringified cell values")


class QueryResult(dx.Model):
    """A tabular query result with its columns, rows, and run metadata.

    Attributes
    ----------
    columns : tuple of str
        The result column names.
    rows : tuple of QueryRow
        The result rows, each a tuple of stringified cells.
    row_count : int
        The number of rows returned (after any display truncation).
    truncated : bool
        Whether more rows matched than were returned.
    elapsed_ms : float
        Wall-clock execution time in milliseconds.
    """

    columns: tuple[str, ...] = dx.field(description="result column names")
    rows: tuple[dx.Embed[QueryRow], ...] = dx.field(
        default_factory=tuple,
        description="result rows of stringified cells",
    )
    row_count: int = dx.field(default=0, description="number of rows returned")
    truncated: bool = dx.field(
        default=False,
        description="whether more rows matched than were returned",
    )
    elapsed_ms: float = dx.field(default=0.0, description="execution time in ms")


def _ident(name: str) -> str:
    """Return a safe DuckDB identifier derived from a file or column name."""
    cleaned = _IDENT_RE.sub("_", name).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned


def _cell(value: _Cell) -> str:
    """Render a DuckDB cell value to a compact display string."""
    if value is None:
        return ""
    return str(value)


class QueryEngine:
    """A DuckDB-backed query engine over materialized corpus views.

    Parameters
    ----------
    connection : duckdb.DuckDBPyConnection
        The DuckDB connection holding the registered views.
    tables : collections.abc.Sequence of str
        The registered view names, in display order.
    """

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        tables: Sequence[str],
    ) -> None:
        self._connection = connection
        self._tables = tuple(tables)

    @classmethod
    def open(cls, data_dir: Path) -> QueryEngine:
        """Open a directory of Parquet views as a queryable engine.

        Every ``*.parquet`` file in ``data_dir`` is registered as a DuckDB view
        named after its file stem, so ``expressions.parquet`` becomes the
        ``expressions`` view.

        Parameters
        ----------
        data_dir : pathlib.Path
            A directory of materialized Parquet views.

        Returns
        -------
        QueryEngine
            An engine over the views found in the directory.

        Raises
        ------
        QueryError
            When the directory does not exist or holds no Parquet views.
        """
        if not data_dir.is_dir():
            msg = f"no such data directory: {data_dir}"
            raise QueryError(msg)
        parquets = sorted(data_dir.glob("*.parquet"))
        if not parquets:
            msg = f"no .parquet views found in {data_dir}"
            raise QueryError(msg)
        connection = duckdb.connect()
        names: list[str] = []
        for path in parquets:
            name = _ident(path.stem)
            escaped = str(path).replace("'", "''")
            connection.execute(
                f"CREATE OR REPLACE VIEW {name} AS "  # noqa: S608
                f"SELECT * FROM read_parquet('{escaped}')"
            )
            names.append(name)
        ordered = [t for t in _PREFERRED_TABLE_ORDER if t in names]
        ordered += [t for t in names if t not in _PREFERRED_TABLE_ORDER]
        return cls(connection, ordered)

    @property
    def tables(self) -> tuple[str, ...]:
        """Return the registered view names in display order."""
        return self._tables

    def columns(self, table: str) -> tuple[str, ...]:
        """Return the column names of a registered view.

        Parameters
        ----------
        table : str
            A registered view name.

        Returns
        -------
        tuple of str
            The view's column names, or an empty tuple when it is unknown.
        """
        if table not in self._tables:
            return ()
        cursor = self._connection.execute(f"SELECT * FROM {table} LIMIT 0")  # noqa: S608
        return tuple(column[0] for column in (cursor.description or ()))

    def schema(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Return every view with its columns, for the schema browser.

        Returns
        -------
        tuple of (str, tuple of str)
            Pairs of view name and its column names, in display order.
        """
        return tuple((table, self.columns(table)) for table in self._tables)

    def run_sql(self, sql: str, *, limit: int = _DEFAULT_ROW_LIMIT) -> QueryResult:
        """Execute read-only DuckDB SQL and return a bounded result.

        Parameters
        ----------
        sql : str
            The SQL statement to run.
        limit : int, optional
            The maximum number of rows to return; one extra row is fetched to
            detect truncation.

        Returns
        -------
        QueryResult
            The columns, rows, count, and truncation flag.

        Raises
        ------
        QueryError
            When the statement is empty or DuckDB rejects it.
        """
        statement = sql.strip().rstrip(";")
        if not statement:
            msg = "empty query"
            raise QueryError(msg)
        start = time.perf_counter()
        try:
            cursor = self._connection.execute(statement)
            fetched = cursor.fetchmany(limit + 1)
        except duckdb.Error as error:
            raise QueryError(str(error)) from error
        columns = tuple(column[0] for column in (cursor.description or ()))
        return _result_from_rows(columns, fetched, limit, start)

    def concordance(  # noqa: PLR0913 - all kwargs are independent KWIC knobs
        self,
        pattern: str,
        *,
        table: str = "expressions",
        column: str = "text",
        window: int = _DEFAULT_KWIC_WINDOW,
        ignore_case: bool = True,
        limit: int = _DEFAULT_ROW_LIMIT,
    ) -> QueryResult:
        """Run a keyword-in-context (KWIC) search over a text column.

        Each match of the regular expression ``pattern`` yields a row of the
        source identifier, the left context window, the matched text, and the
        right context window, so hits read as a classic concordance.

        Parameters
        ----------
        pattern : str
            A Python regular expression to search for.
        table : str, optional
            The view holding the text column.
        column : str, optional
            The text column to search.
        window : int, optional
            The number of context characters to show on each side of a match.
        ignore_case : bool, optional
            Whether to match case-insensitively.
        limit : int, optional
            The maximum number of concordance lines to return.

        Returns
        -------
        QueryResult
            Columns ``source``, ``left``, ``match``, ``right``.

        Raises
        ------
        QueryError
            When the table or column is unknown, or the pattern is invalid.
        """
        if not pattern.strip():
            msg = "empty concordance pattern"
            raise QueryError(msg)
        available = self.columns(table)
        if column not in available:
            msg = f"column {column!r} not found in {table!r}"
            raise QueryError(msg)
        try:
            compiled = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as error:
            msg = f"invalid pattern: {error}"
            raise QueryError(msg) from error
        source = _pick_source_column(available)
        select = f"{source}, {column}" if source else column
        start = time.perf_counter()
        try:
            scan = self._connection.execute(
                f"SELECT {select} FROM {table} "  # noqa: S608
                f"WHERE {column} IS NOT NULL"
            ).fetchall()
        except duckdb.Error as error:
            raise QueryError(str(error)) from error
        rows: list[QueryRow] = []
        total = 0
        for record in scan:
            label = _cell(record[0]) if source else ""
            text = _cell(record[-1])
            for match in compiled.finditer(text):
                total += 1
                if len(rows) < limit:
                    rows.append(_kwic_row(label, text, match, window))
            if len(rows) >= limit and total > limit:
                # keep counting truncation cheaply on the current record only.
                continue
        elapsed = (time.perf_counter() - start) * 1000
        return QueryResult(
            columns=("source", "left", "match", "right"),
            rows=tuple(rows),
            row_count=len(rows),
            truncated=total > len(rows),
            elapsed_ms=elapsed,
        )

    def cql(
        self,
        query: str,
        *,
        table: str = "annotations",
        limit: int = _DEFAULT_ROW_LIMIT,
    ) -> QueryResult:
        """Compile and run a CQL token-pattern over the annotations table.

        A CQL query is a sequence of bracketed token constraints, for example
        ``[label="DET"] [label="NOUN"]`` or ``[subkind="pos" & label="VERB"]``.
        Each constraint matches an annotation attribute (``=`` exact, ``!=``
        negated, ``~`` regular expression); an empty ``[]`` matches any token.
        Adjacent blocks are joined on consecutive ``token_index`` within the same
        layer, so the pattern matches token sequences. Each block matches exactly
        one token; repetition quantifiers (``*``, ``+``, ``?``, ``{...}``) are not
        supported and a pattern that uses one raises :class:`CqlError`.

        Parameters
        ----------
        query : str
            The CQL token-pattern.
        table : str, optional
            The token-aligned annotations view to query.
        limit : int, optional
            The maximum number of matches to return.

        Returns
        -------
        QueryResult
            Columns ``layer_uri``, ``token_index``, and one ``tok{i}`` per block.

        Raises
        ------
        CqlError
            When the pattern is empty, malformed, or references unknown columns.
        QueryError
            When DuckDB rejects the compiled statement.
        """
        available = self.columns(table)
        if not available:
            msg = f"no such table: {table!r}"
            raise CqlError(msg)
        for required in ("layer_uri", "token_index"):
            if required not in available:
                msg = f"table {table!r} is not token-aligned (missing {required!r})"
                raise CqlError(msg)
        blocks = _parse_cql(query, available)
        sql = _compile_cql(blocks, table, has_label="label" in available)
        start = time.perf_counter()
        try:
            cursor = self._connection.execute(sql)
            fetched = cursor.fetchmany(limit + 1)
        except duckdb.Error as error:
            raise QueryError(str(error)) from error
        columns = tuple(column[0] for column in (cursor.description or ()))
        return _result_from_rows(columns, fetched, limit, start)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._connection.close()


def _pick_source_column(columns: Sequence[str]) -> str | None:
    """Return the best identifier column for a concordance row label."""
    for candidate in _SOURCE_COLUMN_PREFERENCE:
        if candidate in columns:
            return candidate
    return columns[0] if columns else None


def _kwic_row(
    label: str,
    text: str,
    match: re.Match[str],
    window: int,
) -> QueryRow:
    """Build a KWIC row from a regex match and its context windows."""
    start, end = match.start(), match.end()
    left = _WHITESPACE_RE.sub(" ", text[max(0, start - window) : start])
    hit = _WHITESPACE_RE.sub(" ", text[start:end])
    right = _WHITESPACE_RE.sub(" ", text[end : end + window])
    return QueryRow(cells=(label, left, hit, right))


def _result_from_rows(
    columns: tuple[str, ...],
    fetched: Sequence[Sequence[_Cell]],
    limit: int,
    start: float,
) -> QueryResult:
    """Assemble a bounded :class:`QueryResult` from fetched DuckDB rows."""
    truncated = len(fetched) > limit
    kept = fetched[:limit]
    rows = tuple(QueryRow(cells=tuple(_cell(value) for value in row)) for row in kept)
    elapsed = (time.perf_counter() - start) * 1000
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=elapsed,
    )


def _parse_cql(
    query: str,
    columns: Sequence[str],
) -> list[list[tuple[str, str, str]]]:
    """Parse a CQL query into per-block constraint lists.

    Parameters
    ----------
    query : str
        The CQL token-pattern.
    columns : collections.abc.Sequence of str
        The columns available on the target table, for validation.

    Returns
    -------
    list of list of (str, str, str)
        One list of ``(attribute, operator, value)`` constraints per token block.

    Raises
    ------
    CqlError
        When no blocks are present, a constraint is malformed or unknown, or a
        repetition quantifier (``*``, ``+``, ``?``, ``{...}``) follows a block.

    Notes
    -----
    Repetition quantifiers are not supported in this release. Each block matches
    exactly one token, and adjacent blocks match consecutive token positions. A
    quantifier following a block raises :class:`CqlError` rather than being
    silently dropped, so an unsupported pattern fails loudly instead of running
    with the quantifier ignored.
    """
    quantifier = _CQL_QUANTIFIER_RE.search(query)
    if quantifier is not None:
        msg = (
            f"repetition quantifier {quantifier.group(1)!r} is not supported; "
            "each token block matches exactly one token"
        )
        raise CqlError(msg)
    blocks = _CQL_BLOCK_RE.findall(query)
    if not blocks:
        msg = 'no token blocks found; write a pattern like [label="VERB"]'
        raise CqlError(msg)
    column_set = set(columns)
    parsed: list[list[tuple[str, str, str]]] = []
    for raw in blocks:
        body = raw.strip()
        constraints: list[tuple[str, str, str]] = []
        if body:
            stripped = _CQL_CONSTRAINT_RE.sub("", body).replace("&", "").strip()
            if stripped:
                msg = f"malformed token constraint near: {stripped!r}"
                raise CqlError(msg)
            for attr, op, value in _CQL_CONSTRAINT_RE.findall(body):
                if attr not in column_set:
                    msg = f"unknown attribute {attr!r}; available: {sorted(column_set)}"
                    raise CqlError(msg)
                constraints.append((attr, op, value))
        parsed.append(constraints)
    return parsed


def _constraint_sql(alias: str, attr: str, op: str, value: str) -> str:
    """Render one CQL constraint to a SQL boolean expression."""
    literal = value.replace("'", "''")
    column = f"{alias}.{attr}"
    if op == "=":
        return f"{column} = '{literal}'"
    if op == "!=":
        return f"{column} <> '{literal}'"
    return f"regexp_matches({column}, '{literal}')"


def _compile_cql(
    blocks: Sequence[Sequence[tuple[str, str, str]]],
    table: str,
    *,
    has_label: bool,
) -> str:
    """Compile parsed CQL blocks into a token-sequence self-join query.

    Adjacent blocks join on consecutive ``token_index`` within the same layer.
    Each block projects its token's ``label`` (when the table carries one) so a
    match reads as the matched token sequence.
    """
    joins: list[str] = [f"{table} a0"]
    wheres: list[str] = ["a0.token_index IS NOT NULL"]
    selects: list[str] = ["a0.layer_uri", "a0.token_index"]
    for index, constraints in enumerate(blocks):
        alias = f"a{index}"
        if index > 0:
            joins.append(
                f"JOIN {table} {alias} ON {alias}.layer_uri = a0.layer_uri "
                f"AND {alias}.token_index = a0.token_index + {index}"
            )
        for attr, op, value in constraints:
            wheres.append(_constraint_sql(alias, attr, op, value))
        if has_label:
            selects.append(f"{alias}.label AS tok{index}")
    return (
        f"SELECT {', '.join(selects)} "  # noqa: S608
        f"FROM {' '.join(joins)} "
        f"WHERE {' AND '.join(wheres)} "
        f"ORDER BY a0.layer_uri, a0.token_index"
    )
