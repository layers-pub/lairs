# Tutorial

This tutorial works through the three operations that define lairs, in order,
on a single running example: reading a published corpus from a Personal Data
Server (PDS), materializing its records into columnar views, and authoring new
records and computing a publish plan. Each chapter builds on the last. Follow
them in sequence. Every step is meant to run as written.

The running example is a small English corpus: one expression record holding the
sentence *The cat sat on the mat.*, with a part-of-speech annotation layer over
it. The same expression and layer reappear in every chapter, so the reading
chapter shows you the records that the materializing chapter turns into Arrow
tables, and the authoring chapter rebuilds equivalents from scratch.

## Prerequisites

Install lairs:

```bash
pip install lairs
```

The reading chapter loads records over ATProto. Public reads need no
authentication: a PDS serves the `com.atproto.repo.listRecords` and
`com.atproto.repo.getRecord` methods to anyone. To follow the reading chapter
against the live network you need an AT-URI whose authority publishes
`pub.layers.*` records. The chapter also shows how to drive the loader from an
injected client so the example runs without any network at all.

The materializing chapter writes Parquet files and reads them back with
[pyarrow](https://arrow.apache.org/docs/python/), which lairs already depends on.
The authoring chapter writes to a local store on disk and computes a publish plan
offline. It sends nothing to any PDS.

## What you will not find here

The tutorial is a single guided path, not a catalog. It does not enumerate the
load sources, the dataset transforms, or the exporter back ends. For those, read
the task-oriented [Guides](../guide/index.md). For the design behind the
generated models, the anchor system, and the store, read the
[Concepts](../concepts/index.md). For per-symbol signatures, read the
[API reference](../reference/index.md).

[Start: reading a corpus](01-reading-a-corpus.md).
