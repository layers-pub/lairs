"""DuckDB query accelerator for the discovery index.

A rebuildable, derived view over the panproto index: cards are materialized to
Parquet and pre-filtered with DuckDB SQL, then the matching cards are loaded
from the index (the source of truth) and ranked by the in-memory scorer, so the
result is identical to ``query.search``. The DuckDB pre-filter is a relaxation
of the full predicate (it never excludes a true match), and the final
``search`` pass applies the exact predicate and ranking. The Parquet is never
authoritative and can be rebuilt from the index at any time.

This module imports DuckDB and pyarrow at module top; it is reached explicitly
as ``lairs.discovery.accelerator`` so that importing ``lairs`` does not pull
DuckDB into every process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from lairs.discovery.query import search

if TYPE_CHECKING:
    from pathlib import Path

    from lairs.discovery.cards import DatasetCard
    from lairs.discovery.index import DiscoveryIndex
    from lairs.discovery.query import SearchHit, SearchQuery

__all__ = ["materialize_cards", "search_accelerated"]

_PARQUET_NAME = "cards.parquet"
"""The file name of the derived columnar card view."""


def _cards_table(cards: list[DatasetCard]) -> pa.Table:
    """Build a flat Arrow table of the card columns DuckDB filters on."""
    return pa.table(
        {
            "corpus_uri": [card.summary.uri for card in cards],
            "name": [card.summary.name for card in cards],
            "description": [card.summary.description for card in cards],
            "domain": [card.summary.domain for card in cards],
            "license": [card.summary.license for card in cards],
            "expression_count": [card.summary.expression_count for card in cards],
        },
    )


def materialize_cards(index: DiscoveryIndex, out_dir: Path) -> Path:
    """Write the index's cards to a Parquet view, returning its path.

    The view is derived and rebuildable: it is regenerated from ``index.cards()``
    on each call and is never the source of truth.

    Parameters
    ----------
    index : lairs.discovery.index.DiscoveryIndex
        The index whose cards to materialize.
    out_dir : pathlib.Path
        The directory to write the Parquet view into.

    Returns
    -------
    pathlib.Path
        The path of the written Parquet file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / _PARQUET_NAME
    pq.write_table(_cards_table(index.cards()), path)
    return path


def search_accelerated(
    index: DiscoveryIndex,
    query: SearchQuery,
    *,
    out_dir: Path,
) -> list[SearchHit]:
    """Search the index through the DuckDB-accelerated pre-filter.

    Materializes the card view, narrows it with a DuckDB SQL pre-filter, loads
    the surviving cards from the index, and ranks them with the same scorer as
    :func:`lairs.discovery.query.search`, so the result is identical to an
    in-memory search over every card.

    Parameters
    ----------
    index : lairs.discovery.index.DiscoveryIndex
        The index to search.
    query : SearchQuery
        The query to apply.
    out_dir : pathlib.Path
        The directory for the rebuildable Parquet view.

    Returns
    -------
    list of SearchHit
        The matching cards, ranked identically to the in-memory search.
    """
    parquet = materialize_cards(index, out_dir)
    clauses: list[str] = []
    params: list[str | int] = [str(parquet)]
    if query.text is not None:
        clauses.append(
            "(lower(name) LIKE ? OR lower(coalesce(description, '')) LIKE ?)"
        )
        like = f"%{query.text.lower()}%"
        params.extend([like, like])
    if query.domain is not None:
        clauses.append("domain = ?")
        params.append(query.domain)
    if query.license is not None:
        clauses.append('"license" = ?')
        params.append(query.license)
    if query.min_expressions is not None:
        clauses.append("expression_count >= ?")
        params.append(query.min_expressions)
    if query.max_expressions is not None:
        clauses.append("expression_count <= ?")
        params.append(query.max_expressions)
    where = " AND ".join(clauses) if clauses else "TRUE"
    sql = f"SELECT corpus_uri FROM read_parquet(?) WHERE {where}"  # noqa: S608
    connection = duckdb.connect()
    try:
        rows = connection.execute(sql, params).fetchall()
    finally:
        connection.close()
    candidates: list[DatasetCard] = []
    for row in rows:
        card = index.get_card(str(row[0]))
        if card is not None:
            candidates.append(card)
    return search(candidates, query)
