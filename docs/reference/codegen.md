# Code generation

The `lairs._codegen` package drives vendored lexicon JSON through
panproto parsing, a schema-to-spec mapping, and module emission, writing
one committed module per `pub.layers.*` namespace into
`lairs.records._generated`. The generated modules are never hand-edited.
Edit this pipeline instead. See [generated models](../concepts/generated-models.md)
for the rationale.

## Pipeline

The top-level driver. `generate` writes the modules and `check` powers
the `lairs gen --check` drift gate.

::: lairs._codegen.pipeline

## Schema to spec

Fuses a parsed panproto `Schema` with its lexicon document into the
codegen intermediate representation: `ModelSpec`, `FieldSpec`, and
`VariantSpec` value models, one per record, object, or formal union.

::: lairs._codegen.schema_to_spec

## Emit

Renders the spec models into deterministic, committed module source
text with a generated-by header and the source manifest hash.

::: lairs._codegen.emit

## Manifest

The vendoring manifest model and loader. The `lexicon_tree_hash` is
stamped into every emitted module.

::: lairs._codegen.manifest
