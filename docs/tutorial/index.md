# Tutorial

Follow a small English corpus through three lairs workflows: reading published
records from a Personal Data Server (PDS), materializing them into columnar
views, and authoring records for a publish plan. The chapters build on one
another, so follow them in sequence. Each step is intended to run as written.

The corpus contains one expression record for *The cat sat on the mat.* and a
part-of-speech annotation layer over it. The same expression and layer appear in
each chapter: first as records read from a PDS, then as rows in Arrow tables, and
finally as newly authored equivalents.

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

## Further documentation

The tutorial follows one guided path. The task-oriented
[Guides](../guide/index.md) cover the available load sources, dataset
transformations, and exporter back ends. For the design behind the generated
models, anchor system, and store, read the
[Concepts](../concepts/index.md). For per-symbol signatures, read the
[API reference](../reference/index.md).

[Start: reading a corpus](01-reading-a-corpus.md).
