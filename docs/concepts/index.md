# Concepts

These pages explain why lairs is shaped the way it is. They are
understanding-oriented: they discuss the design, the trade-offs behind
it, and the alternatives that were rejected. They do not give
step-by-step instructions (the [tutorial](../tutorial/index.md) and the
[guides](../guide/index.md) do that) and they do not enumerate every
symbol (the [API reference](../reference/index.md) does that).

Read them when a guide tells you *how* and you want to know *why*.

- [Architecture](architecture.md): the stack from vendored lexicons
  through codegen, the generated models, the store, and the dataset and
  media layers, then the read flow and the write flow, with the store as
  the hinge between them.
- [Generated models](generated-models.md): why no `pub.layers.*` model
  is hand-written, the lexicon-to-model path, why the lossy theory route
  is not used, and the drift gate that keeps the committed models
  honest.
- [The Layers data model](layers-data-model.md): the record graph of
  expressions, segmentations, annotation layers, anchors, media, and the
  knowledge graph, how records join by AT-URI, and the polymorphic
  `objectRef`.
- [Anchors and modality](anchors-and-modality.md): the polymorphic
  anchor, how the lexicons represent it (an object with optional fields,
  not a tagged union), and how one resolver unifies slicing across text,
  tokens, audio, video, and signals.
- [Reproducibility](reproducibility.md): the didactic Repository as
  schema-aware version control, content addressing, a corpus snapshot as
  a commit and a dataset version as a tag, Arrow views as rebuildable
  derivations, and provenance carried through to exports.
- [Integrations](integrations.md): the ports-and-adapters design, the
  four ports an adapter binds to, the three adapter families, runtime
  entry-point discovery, and why integrations stay out of core.
