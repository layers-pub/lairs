# Code generation

The `lairs._codegen` package passes vendored lexicon JSON through
panproto parsing, schema-to-spec mapping, and module emission. It writes
one committed module per `pub.layers.*` namespace into
`lairs.records._generated`. The generated modules are never hand-edited.
Edit this pipeline instead. See [generated models](../concepts/generated-models.md)
for the rationale.

## Pipeline

The top-level driver exposes `generate`, which writes the modules, and
`check`, which powers the `lairs gen --check` drift gate.

::: lairs._codegen.pipeline

## Schema to spec

The schema-to-spec step combines a parsed panproto `Schema` with its lexicon
document to produce the codegen intermediate representation: `ModelSpec`,
`FieldSpec`, and `VariantSpec` value models, one per record, object, or formal
union.

::: lairs._codegen.schema_to_spec

## Emit

The emitter renders the spec models into deterministic, committed module
source text with a generated-by header and the source manifest hash.

::: lairs._codegen.emit

## Manifest

The manifest module defines the vendoring manifest model and loader. The
`lexicon_tree_hash` is stamped into every emitted module.

::: lairs._codegen.manifest
