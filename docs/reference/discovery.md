# Dataset discovery

Discovery composes identity resolution, the PDS and appview clients, and
the panproto store into a discovery surface over the Layers network. It
spans three tiers: list a single actor's datasets and repository table of
contents, fan out over a seed of actors and resolve cross-repo,
ref-anchored link queries, and build a local, searchable index from the
firehose and a backfill crawl. The discovery shapes carry over the same
record envelopes used to read a PDS; see the
[ATProto reference](atproto.md).

## Single-actor discovery

List an actor's datasets and repository table of contents. Resolves a
handle or DID through the identity resolver and lists the actor's corpora
as summary rows, preferring an appview when one is available.

::: lairs.discovery.actor

## Federated discovery

Network discovery without a central index: given a seed of handles or
DIDs, list every actor's datasets and merge them, and answer
ontology-anchored queries across the seed.

::: lairs.discovery.federated

## Link queries

Cross-repo, ref-anchored queries anchored on a content reference (a
corpus, an eprint) rather than a repository, so an appview that indexes
the network can answer them across actors.

::: lairs.discovery.links

## The discovery index

A searchable index of dataset cards over a panproto Repository. The
`DiscoveryIndex` is a thin behavioral wrapper around the repository,
which remains the source of truth.

::: lairs.discovery.index

## Index ingest

The backfill crawl and firehose tail that populate the index. Both
pipelines write through the panproto Repository, recording one dataset
card per discovered corpus along with the resumable cursor and per-repo
crawl state.

::: lairs.discovery.ingest

## Search

In-memory search over the discovery index: the primary, dependency-free
query path that loads dataset cards, filters them with plain predicates,
and ranks the matches.

::: lairs.discovery.query

## Query accelerator

A rebuildable DuckDB pre-filter over the index. Cards are materialized to
Parquet and pre-filtered with SQL, then the matching cards are loaded
from the index and ranked by the in-memory scorer, so the result is
identical to the plain search.

::: lairs.discovery.accelerator

## Cards

The index record models and the corpus-to-card builder: the `DatasetCard`
stored per discovered corpus and the crawl report that summarizes an
ingest run.

::: lairs.discovery.cards

## Result models

The value types for discovery results: a denormalized corpus summary, a
repository table of contents, a collection count, and a facet filter.

::: lairs.discovery.models

## Summaries

The corpus-to-summary projection and dataset filtering: projects a
generated `Corpus` record into the flat summary shape, evaluates a filter
over a summary, and extracts the server-side facets the appview supports.

::: lairs.discovery.summary
