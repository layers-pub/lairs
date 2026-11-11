# Universal Dependencies and CoNLL-U

`lairs.conllu` reads and writes CoNLL-U exactly, maps it onto Layers records
in the shape the Layers UD importer publishes, and reads Universal
Dependencies treebanks back out of Layers records as typed CoNLL-U rows. It
has four parts:

- `lairs.conllu.model`: the typed `ConlluSentence` and `ConlluRow`.
- `lairs.conllu.text`: streaming `parse` and exact `serialize`.
- `lairs.conllu.projection`: the one mapping between sentences and records.
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

A sentence rebuilt from records in the shape described below is exact. That
is the shape the Layers UD importer publishes once a treebank has been
imported with its lossless importer. A sentence rebuilt from records published
before that is reconstructed from what the records hold, and `sentence.lossy`
names the fields that were reconstructed rather than restored:

| Flag | What was reconstructed |
|---|---|
| `comments` | comments from `id`, `text`, the sorted features, and the enclosing document and paragraph; order, spacing, and valueless comments are lost |
| `misc` | MISC from the sorted published pairs, with `SpaceAfter=No` inferred from adjacent byte spans; item order and the `SpaceAfter` of a sentence's last token are lost |
| `feats` | FEATS regrouped from the morph annotations, with `ud_feats_original` undoing normalisation; layered names (`Number[psor]`) are lost |
| `empty_nodes` | empty nodes from `ud_empty_node` and the enhanced tokenization; their LEMMA, UPOS, XPOS, FEATS, and MISC are lost |
| `multiword_tokens` | ranges from the alignment or shared spans; their MISC order and `SpaceAfter` are reconstructed |
| `deps` | an enhanced arc whose head or dependent could not be identified was dropped |
| `carriers` | the sentence declares residual carriers that are not all present (for example, the carrier layer was not loaded) |

`sentence.exact` is true when `lossy` is empty. A value is never invented: a
field the records do not hold stays `_`.

## The record shape

The projection reads and writes the shape the Layers UD importer publishes.
Its reader contract, `docs/ud-reader-contract.md` in `layers-repo`, is the
specification, and `lairs` tests its reader against records that importer
built. In outline, per sentence:

| CoNLL-U | Where it lives |
|---|---|
| comment lines | `ud_comment` entries on the sentence `Expression`'s `features`, verbatim and in order, after a `ud_comment_lines` count |
| FORM | token `text` in the word tokenization |
| LEMMA, UPOS, XPOS | `lemma`, `pos`, and `xpos` token-tag layers |
| FEATS | a `morph` layer with one annotation per value, labelled with the full key (`Number[psor]=Sing`); `ud_feats_original` holds the source pair when it was normalised |
| HEAD, DEPREL | a `dependency` relation layer |
| DEPS | an `enhanced-dependency` layer over the enhanced tokenization (the words, then the empty nodes) |
| MISC | a `misc` token-tag layer whose annotation `value` is the column verbatim |
| multiword-token lines | `multiword-token` links of a `word-to-word` alignment, with the line's FEATS and MISC verbatim in `ud_feats` and `ud_misc` |
| empty nodes | tokens of the enhanced tokenization after the words, with `pos`, `xpos`, `lemma`, `morph`, and `misc` layers over them; every annotation carries `ud_empty_node` with the `n.m` id |

Other feature entries on these records (the `key = value` comments, the parsed
MISC items on dependency annotations and links, `feats:<Key>`) are a
queryable view. The reader never rebuilds from them.

### Long values

Feature values and annotation values are limited to 4096 UTF-8 bytes. A longer
value is split at character boundaries into an entry `K` followed by entries
`K+`, which are joined in order. An over-long MISC column is the annotation
`value` followed by `ud_misc+` entries.

### Residual carriers

That shape holds every valid UD sentence, so a valid sentence projects to
records with nothing added. Some input still parses as CoNLL-U but does not
fit: rows out of canonical order, a HEAD with no DEPREL, or a FEATS key that
recurs after another key. For that input only, `Projector` adds residual
carriers, so that the local round trip stays exact:

| Where | Key | Value |
|---|---|---|
| sentence `Expression` | `conllu:scheme` | `1` |
| sentence `Expression` | `conllu:order` | the row ids in source order, space-separated, when the rows are not in canonical order |
| sentence `Expression` | `conllu:rows` | the number of annotations in the carrier layer, when it is not zero |
| carrier layer annotation | `conllu:<column>` | the column's exact text, for each column the shape does not restore |
| carrier layer annotation | `conllu:drop` | `true`, for a row the shape implies but the source lacks |

The carrier layer is an `AnnotationLayer` with `kind="token-tag"` and
`subkind="conllu"`, and each annotation's `label` is its row id. A long value
continues in `conllu:more` entries. Canonical order puts each range just
before its first word and each empty node `n.m` just after word `n`.
`Projector(carriers=False)` leaves the residual carriers out.

### Adopting the seams

`Projector` takes the record naming (`RecordNaming`), the ontology references
and FEATS normalisation (`OntologyResolver`), `created_at`, `languages`,
`source_method`, `corpus_ref`, `split`, and the alignment `tool` as
parameters. `OntologyResolver.feat` receives the full FEATS key, layer
included, and a resolver that normalises a pair returns the source pair in an
`ud_feats_original` entry. `NoOntology` and `LocalNaming` are the neutral
defaults.
