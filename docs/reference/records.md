# Records

The record surface: the `BlobRef` value type, the generated-safe view
helpers, and the generated `pub.layers.*` record namespaces. The
namespace modules under `lairs.records._generated` are emitted by `lairs
gen` from the vendored lexicons and must not be hand-edited. See [code
generation](codegen.md).

## Blob reference

::: lairs.records.blobref.BlobRef

## View helpers

Behavior over the generated models, never replacements for them.

::: lairs.records.views.anchor_kind

::: lairs.records.views.explode_layer

## Generated record namespaces

One module per `pub.layers.*` namespace. Each class mirrors a lexicon
record, object, or union definition. Unions render as `dx.TaggedUnion`
families with their discriminator. Permission-set (OAuth scope) lexicons
and method-only namespaces (query, procedure, subscription) contribute no
record types and emit no module.

The shared provenance models that the produce records embed live in
`defs`: `Licensing` (an optional SPDX `expression` plus an array of
`LicenseRef`, covering single, dual, multi, composite, and
component-scoped licensing) and `ReproducibilityInfo` (code URI, commit,
command, environment, seed). The bibliographic models live in `eprint`:
`Citation` (a raw string and/or structured CSL-JSON / DataCite fields),
`Creator` (CSL name parts plus DataCite `nameType` / `affiliation` and
ORCID / ROR grounding), and `Date` (structured or free-form, CSL style).

### alignment

::: lairs.records._generated.alignment

### annotation

::: lairs.records._generated.annotation

### changelog

::: lairs.records._generated.changelog

### corpus

::: lairs.records._generated.corpus

### defs

::: lairs.records._generated.defs

### eprint

::: lairs.records._generated.eprint

### expression

::: lairs.records._generated.expression

### graph

::: lairs.records._generated.graph

### judgment

::: lairs.records._generated.judgment

### media

::: lairs.records._generated.media

### ontology

::: lairs.records._generated.ontology

### persona

::: lairs.records._generated.persona

### resource

::: lairs.records._generated.resource

### segmentation

::: lairs.records._generated.segmentation
