# Concepts

These pages describe the design of lairs, the trade-offs behind it, and
the alternatives that were rejected. For step-by-step instructions, see
the [tutorial](../tutorial/index.md) and the [guides](../guide/index.md).
For individual symbols, see the [API reference](../reference/index.md).

- [Architecture](architecture.md): the stack from vendored lexicons to
  generated models, the read and write flows, and the store that connects
  them to the dataset and media layers.
- [Generated models](generated-models.md): why no `pub.layers.*` model
  is hand-written, the lexicon-to-model path, why the lossy theory route
  is not used, and the drift gate.
- [The Layers data model](layers-data-model.md): the record graph, its
  AT-URI joins, and the polymorphic `objectRef` used across records.
- [Anchors and modality](anchors-and-modality.md): the polymorphic anchor,
  its representation as an object with optional fields, and resolution
  across text, tokens, audio, video, and signals.
- [Reproducibility](reproducibility.md): schema-aware version control,
  content addressing, rebuildable Arrow views, and provenance in exports.
- [Integrations](integrations.md): the ports-and-adapters design, adapter
  families, runtime entry-point discovery, and the boundary between core
  and optional dependencies.
