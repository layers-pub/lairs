# The Layers data model

A Layers corpus is not a table. It is a graph of records, joined by
AT-URI, with annotations anchored into text, tokens, time, or space, and
media held by reference. The store and dataset layers are built around
that graph-and-anchor structure rather than a flat row shape. This page
describes the shape the generated models represent, faithful to the
lexicons they are generated from.

The model descriptions here summarise the lexicons. The authoritative
form is the generated code under `lairs.records`, and the lexicons it is
generated from under `lairs/lexicons/pub/layers/`.

## Expressions: the document spine

The `expression.expression` record is the primary document model. An
expression is any linguistic unit (a document, a transcript, a
paragraph, a sentence, a word, a morpheme) and expressions nest
recursively through a `parentRef` AT-URI, so structural hierarchy is
expressed as a tree of expression records rather than as nested markup.
A top-level expression (a document, a recording) has no `parentRef`.

An expression carries several things. It holds its raw `text`, against
which every byte-offset span is measured, an open `kind` slug
(`document`, `sentence`, `word`, and so on), a primary `language`, and an
optional list of additional `languages` for code-switching. It also holds
references outward to media (`mediaRef`), to a parent (`parentRef`), and
to external resources (`sourceUrl`, `sourceRef`). It may carry an inline
`mediaBlob`, which lairs represents as a `BlobRef` rather than inlining
the bytes.

## Segmentations: token-level decomposition

Structural hierarchy is the expression tree. Token-level decomposition
is the `segmentation.segmentation` record. A segmentation binds one or
more *tokenizations* to an expression, each tokenization carrying a UUID.
Multiple segmentations can coexist for one expression, so alternative
tokenization strategies live side by side rather than overwriting one
another. A token-aligned annotation layer names the tokenization it
aligns to by that UUID.

## Annotation layers: one record type, many kinds

All annotation in Layers flows through a single record type,
`annotation.annotationLayer`. A layer applies to one expression
(`expression`, an AT-URI), and carries an array of annotations plus three
slugs that tell a consumer how to interpret them:

- `kind`: the structural interpretation, one of `token-tag`, `span`,
  `relation`, `tree`, `graph`, `tier`, or `document-tag`.
- `subkind`: the specialisation (`pos`, `ner`, `lemma`, `dependency`,
  `coreference`, `frame`, and many more).
- `formalism`: the standard or theory used (`universal-dependencies`,
  `propbank`, `framenet`, `amr`, `conll-u`, and so on).

A single abstract annotation object carries whatever fields its layer's
kind requires. Token tags use `tokenIndex` and `label`, spans use an
`anchor` and `label`, trees use `parentId` and `childIds`, dependency arcs
use `headIndex` and `targetIndex`, and predicate-argument structures use
`arguments`. This is deliberate. Rather than a separate record type per
annotation shape, Layers has one shape whose populated fields depend on
the layer kind, and lairs generates one model accordingly. A token-aligned
layer names its tokenization through `tokenizationId`, and a layer can
refine or rank another through `parentLayerRef`, `alternativesRef`, and
`rank`.

## Anchors: how annotations attach

An annotation attaches to its source data through an `anchor`. The anchor
is polymorphic: a byte span in text, a single token reference, a
non-contiguous token-reference sequence, a temporal span in audio or
video, a spatio-temporal region with keyframes, a page region in a
document, or an external web target. Crucially, the lexicon models the
anchor as an *object with optional fields*, one per variant, where a
consumer dispatches on which field is populated, not as a formal tagged
union. The [anchors-and-modality](anchors-and-modality.md) page explains
that choice and how lairs resolves an anchor to the slice it points at.

## Media: held by reference

Audio, video, image, and document data live in `media.media` records.
A media record carries a `kind`, a `blob` (up to 100 MB) or an
`externalUri`, a `durationMs`, and composable modality-specific metadata
objects (`audio`, `video`, `document`). Clips reference a parent through
`parentMediaRef` and `startOffsetMs`. Expressions and annotations point
at media by AT-URI. The bytes are fetched on demand and cached by content
identifier, never carried inside the record graph.

## The knowledge graph

On top of the linguistic records sits a property graph. `graph.graphNode`
records stand for entities, concepts, situations, and claims that have no
other Layers record, while existing records are implicitly nodes through
`objectRef`. `graph.graphEdge` and `graph.graphEdgeSet` records carry
typed, directed edges whose endpoints are `objectRef`s. Grounding to
external knowledge bases hangs off the graph and off individual records
through `knowledgeRef`, which names a source (Wikidata, WordNet,
FrameNet, and others) and an identifier within it.

## Joined by AT-URI

Nearly every record points at others by AT-URI. An annotation layer
names its expression, an expression names its parent and its media, a
segmentation names its expression, and edges name their endpoints. The
corpus is the graph these references induce.

Two consequences follow. First, the in-memory `ModelPool` is addressed by
AT-URI and resolves references back to model instances, with
back-reference queries answered by walking the loaded records. Second,
resolution must degrade gracefully: an AT-URI may point at a record not
in the pulled set, so a reference that cannot be resolved is kept as its
string rather than raising. A corpus is rarely complete, and a missing
target is a normal condition, not an error.

## The universal cross-reference: objectRef

`objectRef` is the polymorphic cross-reference primitive, used by graph
nodes, alignment endpoints, annotation dependencies, and any other
pointer that must reach across the three scopes Layers distinguishes:

- `localId`: a UUID of an object *within the same record* (for example
  one annotation referring to another in the same layer).
- `recordRef` (with optional `objectId`): an AT-URI of *another
  record*, optionally narrowed to a UUID inside it.
- `knowledgeRef`: an *external* knowledge-base entry.

Like the anchor, `objectRef` is a lexicon object with optional fields,
and a consumer dispatches on which are populated. This is what lets a
single reference shape span an in-record pointer, a cross-record link,
and an external grounding without three separate types.

The shape that matters for the rest of the system is this: a corpus is a
graph of records joined by AT-URI, annotations anchored into
text/token/time/space, and media held by reference. The store
([reproducibility](reproducibility.md)) and the dataset and media layers
([anchors and modality](anchors-and-modality.md)) are built on that
shape.
