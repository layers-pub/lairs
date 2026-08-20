# Explorer TUI

The `lairs.tui` package provides a Textual application for discovering,
browsing, and querying Layers data. It has four surfaces: an Explore screen
over the discovery index, a Discover screen that crawls configured sources
to index datasets, a type-aware
Browse screen over a local repository, and a Query workbench over
materialized Parquet views. The pure-Python query engine also works
without the terminal stack. For usage, see
[Guides > The explorer TUI](../guide/explorer.md).

## Application

`run_tui` launches the full application, and `QueryEngine` is the
DuckDB-backed query engine that the Query screen drives. The query
result models (`QueryResult`, `QueryRow`) and errors (`QueryError`,
`CqlError`) are also part of the public package surface.

::: lairs.tui

## Visualizations

These text-mode renderers turn Layers records into terminal-friendly
views: interlinear token tags, CoNLL-U grids, dependency trees,
brat-style span overlays, judgment distributions, tier timelines,
alignment bitexts, and the anchor and syntax helpers they share.

::: lairs.tui.viz

## Record views

`lairs.tui.views` dispatches views through the lexicon's own type system. It
defines the views available for a record, the columns for a record list, and
the rendering of a record through one focused view at a time.

::: lairs.tui.views

## Record registry

The registry maps `pub.layers.*` NSIDs to generated record models. Its
namespace and short-label helpers group records in the Browse type tree.

::: lairs.tui.registry

## Screen panes

The application uses composable panes and modal screens: an
`ExplorePane` over the discovery index, a `DiscoverPane` that crawls the
configured sources to index datasets, a `BrowsePane` over a local
repository, a `QueryPane` over the materialized views, and a
`SettingsScreen` for reviewing sources and unmuting datasets.

::: lairs.tui.screens
