"""Interactive terminal UI for exploring and querying Layers data.

The TUI is a colorful Textual application with three surfaces: an Explore screen
that browses and filters the discovery index, a Browse screen that explores
every record in a local repository through type-aware views, and a Query screen
that runs powerful searches over materialized data through three query modes
(DuckDB SQL, a KWIC concordance, and a CQL token-pattern language). The
pure-Python query engine in :mod:`lairs.tui.query` is usable on its own;
:func:`run_tui` launches the full application.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

from lairs.tui.app import LairsApp
from lairs.tui.browse import BrowseError, RepoBrowser, materialize_repo
from lairs.tui.query import (
    CqlError,
    QueryEngine,
    QueryError,
    QueryResult,
    QueryRow,
)

__all__ = [
    "CqlError",
    "QueryEngine",
    "QueryError",
    "QueryResult",
    "QueryRow",
    "run_tui",
]


def _materialize_for_query(repo_path: str) -> str | None:
    """Flatten a repository into a temporary Parquet directory for the Query tab.

    The Browse tab reads the repository directly; the Query tab needs Parquet
    views, so a repository opened on its own is materialized once into a scratch
    directory. The scratch directory is removed at interpreter exit so each
    invocation does not leave a materialized corpus copy in the system temp dir.
    Returns the directory, or ``None`` when the repository cannot be flattened
    (the Browse tab still works in that case).
    """
    try:
        browser = RepoBrowser.open(Path(repo_path))
    except BrowseError:
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="lairs-tui-"))
    atexit.register(shutil.rmtree, out_dir, ignore_errors=True)
    try:
        materialize_repo(browser.repo, out_dir)
    except OSError, ValueError:
        shutil.rmtree(out_dir, ignore_errors=True)
        return None
    return str(out_dir)


def run_tui(
    *,
    index_path: str | None = None,
    data_path: str | None = None,
    repo_path: str | None = None,
) -> None:
    """Launch the Layers explorer TUI.

    Parameters
    ----------
    index_path : str or None, optional
        Filesystem path to a discovery index directory to open on the Explore
        screen. When omitted the Explore screen starts empty.
    data_path : str or None, optional
        Filesystem path to a directory of materialized Parquet views to open on
        the Query screen. When omitted, a repository given by ``repo_path`` is
        materialized to feed the Query screen; otherwise it starts empty.
    repo_path : str or None, optional
        Filesystem path to a local Repository to open on the Browse screen. When
        given without ``data_path``, the repository is also flattened to back the
        Query screen.
    """
    resolved_data = data_path
    if resolved_data is None and repo_path is not None:
        resolved_data = _materialize_for_query(repo_path)

    LairsApp(
        index_path=index_path,
        data_path=resolved_data,
        repo_path=repo_path,
    ).run()
