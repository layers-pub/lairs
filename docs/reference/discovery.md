# Dataset discovery

Discovery combines identity resolution, the PDS and appview clients, and
the panproto store. It supports three scopes: listing one actor's datasets
and repository table of contents; querying a seed of actors, including
cross-repo link queries anchored by references; and building a local,
searchable index from the firehose and a backfill crawl. Discovery uses the
same record envelopes as PDS reads; see the
[ATProto reference](atproto.md).

## Single-actor discovery

Single-actor discovery resolves a handle or DID through the identity
resolver, then lists the actor's datasets and repository table of contents.
It returns corpora as summary rows, preferring an appview when one is
available.

::: lairs.discovery.actor

## Federated discovery

Federated discovery works without a central index. Given a seed of
handles or DIDs, it lists and merges every actor's datasets and answers
ontology-anchored queries across the seed.

::: lairs.discovery.federated

## Link queries

These cross-repo queries are anchored on a content reference, such as a
corpus or an eprint, rather than on a repository. An appview that indexes
the network can thus answer them across actors.

::: lairs.discovery.links

## The discovery index

The discovery index stores searchable dataset cards in a panproto
Repository. `DiscoveryIndex` is a behavioral wrapper around that repository,
which remains the source of truth.

::: lairs.discovery.index

## Index ingest

The backfill crawl and firehose tail populate the index. Both pipelines
write through the panproto Repository, recording one dataset
card per discovered corpus along with the resumable cursor and per-repo
crawl state.

::: lairs.discovery.ingest

## Search

The primary, dependency-free query path searches the discovery index in
memory. It loads dataset cards, filters them with plain predicates, and
ranks the matches.

::: lairs.discovery.query

## Query accelerator

The query accelerator adds a rebuildable DuckDB pre-filter over the index.
Cards are materialized to Parquet and pre-filtered with SQL. The matching
cards are then loaded from the index and ranked by the in-memory scorer, so
the result is identical to the plain search.

::: lairs.discovery.accelerator

## Cards

The index record models include the `DatasetCard` stored per discovered
corpus and the crawl report that summarizes an ingest run. The same module
provides the corpus-to-card builder.

::: lairs.discovery.cards

## Result models

Discovery result types include a denormalized corpus summary, a repository
table of contents, a collection count, and a facet filter.

::: lairs.discovery.models

## Summaries

Summary helpers project a generated `Corpus` record into the flat summary
shape, evaluate a dataset filter over a summary, and extract the server-side
facets that the appview supports.

::: lairs.discovery.summary
