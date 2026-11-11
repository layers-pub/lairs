# Universal Dependencies and CoNLL-U

`lairs.conllu` reads and writes CoNLL-U exactly, maps it onto Layers records
in the shape the Layers UD importer publishes, and reads Universal
Dependencies treebanks back out of Layers records as typed CoNLL-U rows. It
has four parts:

- `lairs.conllu.model`: the typed `ConlluSentence` and `ConlluRow`.
- `lairs.conllu.text`: streaming `parse` and exact `serialize`.
- `lairs.conllu.projection`: the one mapping between sentences and records,
  with lossless carriers.
- `lairs.conllu.reader`: `sentences`, which yields sentences from a corpus.

The `conllu-ud` codec (see [Format codecs](codecs.md)) is built on the same
parts.

## Reading a treebank from Layers records

`lairs.conllu.sentences` takes a loaded `Corpus` or a raw mapping from AT-URI
to record JSON, such as `Repository.content_at(revision)` returns for a pulled
dataset:

```python
from pathlib import Path

import lairs
from lairs.store.repository import Repository

repo = Repository.open(Path("ud-store"))
records = repo.content_at(repo.head())
corpus_uri = "at://did:plc:.../pub.layers.corpus.corpus/..."

for sentence in lairs.conllu.sentences(records, corpus=corpus_uri, split="dev"):
    sentence.sent_id, sentence.text, sentence.comments
    for row in sentence.rows:        # words, multiword ranges, empty nodes
        row.id, row.form, row.lemma, row.upos, row.xpos
        row.feats, row.head, row.deprel, row.deps, row.misc
```

The reader indexes the records once, grouping segmentations, alignments, and
annotation layers by the expression they reference, and rebuilds each
sentence from its records' JSON. It never validates a record into its
generated model, so the cost per sentence is a small multiple of decoding the
JSON. A `Corpus` works too: its pooled models are dumped to JSON once each,
which costs more than reading raw JSON.

Sentences come in membership order (`ordinal`). `corpus` selects the
memberships of one corpus by its AT-URI (a `Corpus` defaults to its own
`uri`), and `split` keeps one split. When the records hold no membership at
all, sentences come in source order. Document and paragraph expressions are
not sentences.

The alignment records that link multiword tokens to their words are used when
they are present. Without them, a multiword range is recovered from words that
share one byte span.

## Typed rows

A `ConlluSentence` stores the sentence's exact lines and exposes typed views:

| View | Type | Notes |
|---|---|---|
| `sentence.comments` | `tuple[Comment, ...]` | every comment line in order, with `key`, `value`, and the verbatim `text` |
| `sentence.sent_id`, `sentence.text` | `str` or `None` | the `# sent_id` and `# text` values |
| `sentence.rows` | `tuple[ConlluRow, ...]` | words, ranges, and empty nodes in source order |
| `row.id` | `RowId` | `kind` is `word`, `range`, or `empty`; `major`, `end`, `minor` are the integer parts |
| `row.form` | `str` | never absent; `_` is the underscore token |
| `row.lemma` | `str` or `None` | `_` is literal when the FORM is `_`, else absent |
| `row.upos`, `row.xpos`, `row.deprel` | `str` or `None` | `None` for `_` |
| `row.feats` | `tuple[Feat, ...]` | `name` keeps the layer (`Number[psor]`), `value` keeps commas (`Acc,Dat`) |
| `row.head` | `int` or `None` | `0` is the root |
| `row.deps` | `tuple[Dep, ...]` | `head` is a `RowId`, possibly an empty node |
| `row.misc` | `tuple[MiscItem, ...]` | every item in order, duplicates and bare items (`value is None`) included |

Rows and their values are built only when read, and the small value models
are shared across a treebank, so iterating a large corpus stays cheap.

## Exact text

`parse` streams sentences from a string or any iterable of lines, so a large
file is never held in memory:

```python
from lairs.conllu import parse, serialize

with open("en_ewt-ud-train.conllu", encoding="utf-8", newline="\n") as handle:
    for sentence in parse(handle):
        ...

assert serialize(parse(text)) == text
```

The round trip is byte-exact for well-formed CoNLL-U in canonical framing: LF
line endings and one blank line after each sentence. Parsing normalises
framing and nothing else. CRLF becomes LF, a leading byte-order mark is
dropped, runs of blank lines collapse to one, and a missing final blank line
is supplied. A malformed line raises `ConlluSyntaxError`, whose `line` is the
1-based line number in the source.

## Fidelity

A sentence rebuilt from records that carry the lossless carriers (described
below) is exact. A sentence rebuilt from records without them, as the Layers
UD importer publishes them today, is reconstructed from what the records hold,
and `sentence.lossy` names the fields that were reconstructed rather than
restored:

| Flag | What was reconstructed |
|---|---|
| `comments` | comments from `id`, `text`, the sorted features, and the enclosing document and paragraph; order, spacing, and valueless comments are lost |
| `misc` | MISC from the sorted published pairs, with `SpaceAfter=No` inferred from adjacent byte spans; item order and the `SpaceAfter` of a sentence's last token are lost |
| `feats` | FEATS regrouped from the morph annotations, with `ud_feats_original` undoing normalisation; layered names (`Number[psor]`) are lost |
| `empty_nodes` | empty nodes from `ud_empty_node` and the enhanced tokenization; their LEMMA, UPOS, XPOS, FEATS, and MISC are lost |
| `multiword_tokens` | ranges from the alignment or shared spans; their MISC order and `SpaceAfter` are reconstructed |
| `deps` | an enhanced arc whose head or dependent could not be identified was dropped |
| `carriers` | the sentence declares carriers that are not all present (for example, the carrier layer was not loaded) |

`sentence.exact` is true when `lossy` is empty. A value is never invented: a
field the records do not hold stays `_`.

## The lossless carrier encoding

The projection emits the published shape plus carriers for exactly what that
shape loses. The carriers never change the meaning of a published field. They
are extra `features` entries whose keys start with `conllu:`, and one extra
annotation layer with its own subkind. This section specifies them so that
other producers, the Layers UD importer among them, can emit them too.

### On the sentence expression

Appended to the sentence `Expression`'s `features`, after the published
entries:

| Key | Value | When |
|---|---|---|
| `conllu:scheme` | `1` | always; the sentence carries carriers of this scheme |
| `conllu:comment` | the comment line after its `#`, verbatim | once per comment line, in order |
| `conllu:comment-ref` | `sent_id` or `text` | in place of a `conllu:comment` entry when the line is exactly `# sent_id = <id>` or `# text = <text>` for the expression's own `id` or `text` |
| `conllu:order` | the row ids in source order, space-separated | only when the rows are not in canonical order |
| `conllu:rows` | the number of annotations in the carrier layer | only when it is not zero |

Canonical order puts each range just before its first word and each empty node
`n.m` just after word `n`.

### The carrier layer

One `AnnotationLayer` with `kind="token-tag"`, `subkind="conllu"`,
`labelSet="conllu-columns"`, and `formalism="universal-dependencies"`, on the
word tokenization. It holds one annotation per row whose columns the published
shape does not restore exactly, and is omitted when there are none:

| Field | Value |
|---|---|
| `label` | the row id: `3`, `1-2`, or `3.1` |
| `tokenIndex`, `anchor` | the word's index, for a word row only |
| `features` | `conllu:<column>` = the column's exact text, for each column the published shape gets wrong |

The column keys are `conllu:form`, `conllu:lemma`, `conllu:upos`,
`conllu:xpos`, `conllu:feats`, `conllu:head`, `conllu:deprel`, `conllu:deps`,
and `conllu:misc`. A row the published shape implies but the source lacks gets
`conllu:drop` = `true`.

The forward projection decides which rows need an annotation by rebuilding the
sentence from its own published-shape records and comparing the result with
the source, column by column. A reader therefore rebuilds every row from the
published layers and then overwrites the carried columns.

### Long values

`Feature.value` is limited to 4096 UTF-8 bytes. A longer carrier value is split
at character boundaries, and each further piece follows as a `conllu:more`
entry, whose value is appended to the entry before it.

### Adopting the seams

`Projector` takes the record naming (`RecordNaming`), the ontology references
and FEATS normalisation (`OntologyResolver`), `created_at`, `languages`,
`source_method`, `corpus_ref`, `split`, and the alignment `tool` as
parameters. With a naming that returns `f"{stem}/{sent_id}/{role}"` and
`f"at://local/{local_id}"`, and a resolver that wraps the importer's ontology
registry, `Projector(carriers=False)` reproduces the importer's records, and
`Projector()` adds the carriers. `NoOntology` and `LocalNaming` are the neutral
defaults.
