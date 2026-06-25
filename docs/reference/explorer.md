# Explorer TUI

The interactive terminal user interface for discovering, browsing, and
querying Layers data. The `lairs.tui` package is a Textual application
with three surfaces: an Explore screen over the discovery index, a
type-aware Browse screen over a local repository, and a Query workbench
over materialized Parquet views. The pure-Python query engine is usable
on its own, without the terminal stack. For usage see
[Guides > The explorer TUI](../guide/explorer.md).

## Application

`run_tui` launches the full application, and `QueryEngine` is the
DuckDB-backed query engine that the Query screen drives. The query
result models (`QueryResult`, `QueryRow`) and errors (`QueryError`,
`CqlError`) round out the public surface of the package.

::: lairs.tui

## Visualizations

Text-mode renderers that turn Layers records into terminal-friendly
views: interlinear token tags, CoNLL-U grids, dependency trees,
brat-style span overlays, judgment distributions, tier timelines,
alignment bitexts, and the anchor and syntax helpers they share.

::: lairs.tui.viz

## Record views

Model-driven view dispatch over the lexicon's own type system: the views
available for a record, the columns for a record list, and the rendering
of a record through a single focused view at a time.

::: lairs.tui.views

## Record registry

The map from `pub.layers.*` NSIDs to generated record models, with the
namespace and short-label helpers that group records in the Browse type
tree.

::: lairs.tui.registry

## Screen panes

The three composable panes that make up the application: an `ExplorePane`
over the discovery index, a `BrowsePane` over a local repository, and a
`QueryPane` over the materialized views.

::: lairs.tui.screens
