# Generated models

No `pub.layers.*` model in lairs is written by hand. Every record type,
every nested object, and the one formal union are generated from the
vendored Layers lexicons and committed to the repository. This constraint
keeps the path from lexicon to `dx.Model` explicit and supports a
byte-exact drift check of the committed models.

## Why generated, never authored

The Layers lexicons are the single source of truth for the schema. There
is no second description of it anywhere in lairs. A hand-written model
would be a second description that could drift from the lexicon it
claims to mirror. Generation avoids maintaining these competing schema
descriptions: the committed models are a pure function of the vendored
lexicons, and updating to a new Layers version is a mechanical sequence
rather than a model-by-model edit. Re-vendor the lexicons, regenerate,
and run the drift check.

This is a hard rule, not a preference. Behavior over the generated
models (builders, view helpers, anchor dispatch) is ordinary code and
lives outside the generated tree. Anything that mirrors the schema is
generated. Anything that is behavior over the schema is not. The
`anchor_kind` helper and the `explode_layer` helper in `lairs.records`
are behavior. The `Anchor` and `AnnotationLayer` classes are generated.

## The path from lexicon to model

A lexicon document becomes committed Python in four stages.

```text
lexicon JSON
  -> panproto.parse_atproto_lexicon(doc)   parse to a Schema
  -> Schema + document  ->  spec models     lairs._codegen.schema_to_spec
  -> emitted module text                    lairs._codegen.emit
  -> lairs/records/_generated/<ns>.py       committed, ruff-canonicalized
```

panproto parses each lexicon into a `Schema` under its built-in
`atproto` protocol. The Schema is the parsed, structured form: it
retains the union discriminators, the refined value types, the
reference-versus-containment edge distinction, and the integer ranges.

lairs then walks the lexicon into a sequence of *spec models*: the
`FieldSpec`, `VariantSpec`, and `ModelSpec` value types, which are
themselves `dx.Model`s, because the codegen intermediate representation
is data like everything else in lairs. One spec is produced per record,
per nested object, and per formal union. The spec carries the
description, the optionality (whether a property is in the lexicon's
`required` set), the refined type, the integer range, the `knownValues`
of an open string enum, and, for a union, its discriminator and members.

The spec mapping reads its structure from the **lexicon document**, not
from the parsed Schema. The document retains the `required` sets and the
field descriptions that
the Schema graph does not surface, and it preserves definition order. The
Schema is parsed and accepted (which asserts that the document parses
cleanly under the `atproto` protocol) but the field-by-field walk is
driven by the JSON. The two sources are complementary: the parse is the
correctness check, the document is the data.

The emitter renders each spec to module text, the pipeline injects the
cross-namespace imports a module needs (for instance `annotation`
embedding `defs#anchor`), and a `ruff format` then `ruff check --fix`
then `ruff format` pass converges the output to a stable, lint-clean
form. A fresh generation can thus be compared byte-for-byte against
the committed modules.

## Why not the lossy theory path

panproto can also induce a categorical *theory* from a Schema, and
didactic can synthesize models from a theory. That route is shorter, and
it is not used. The induced theory is lossy by design: it cannot express
refined value types, per-field defaults and descriptions, or the
reference-versus-containment distinction, and it drops union
discriminators, so a model rebuilt from a theory cannot reconstruct a
tagged union. didactic's own spec-dict synthesizer is closer but still
discards descriptions, defaults, optionality, refined types, and the
embed-versus-ref distinction.

Because lairs needs every one of those properties in the committed
output, it does not route through either. Instead, it walks the lexicon
into spec models, which the emitter renders directly. The theory path
remains useful for a quick structural check but is not the generation
path.

The distinction is most visible in the union. The Layers lexicons contain
a single formal `union`: the `selector` of `defs#externalTarget`,
over the three W3C selector types. It generates a `dx.TaggedUnion`
(`ExternalTargetSelector`) with a `kind` discriminator and one member
class per reference. Had codegen gone through the theory, the
discriminator would have been lost and the union could not have been
rebuilt. A focused codegen test asserts that the lexicon union
round-trips to a tagged union with its discriminator intact.

Note what is *not* a tagged union. The polymorphic `anchor` and the
universal `objectRef` are lexicon *objects* with several optional fields,
where a consumer dispatches on which fields are populated, not formal
unions over refs. They generate as ordinary `dx.Model`s with optional
fields, faithfully to the lexicon. The
[anchors-and-modality](anchors-and-modality.md) page explains why the
lexicons model anchors this way and how lairs dispatches on them.

## The drift gate

The generated modules are committed rather than generated at install
time. Committing them provides import speed, IDE and type-checker support,
and reviewable diffs when a Layers version is bumped. The committed
modules must thus stay faithful to the vendored lexicons.

`lairs gen --check` enforces this requirement. It regenerates the modules
into a temporary directory from the vendored lexicons and compares them
byte-for-byte against the committed modules. Any difference fails. Each
generated module carries a header recording the lexicon-tree hash it was
produced from, and the same hash lives in the manifest. The
canonicalization pass makes this comparison byte-exact rather than merely
semantically equivalent.

For the operational steps (vendoring a lexicon tree, regenerating, and
running the check) see the [codegen guide](../guide/codegen.md).
