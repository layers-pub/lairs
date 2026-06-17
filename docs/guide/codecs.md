# Codecs: external annotation formats

This guide covers decoding external annotation formats into Layers records and
encoding records back, through the `Codec` port. It documents the bundled
CoNLL-U and brat codecs, the `CorpusFragment` they pivot through, the round-trip
`Iso` fixtures, and which extras each codec needs.

A codec is a bidirectional converter between an external format and lairs
records, bound to the `Codec` protocol in `lairs.integrations.ports`. It
translates an external format's spans and labels into lairs anchors and one of
the annotation kinds, and lairs owns the rest. Resolve a codec by name through the
registry:

```python
import lairs

ConlluCodec = lairs.codec("conllu")
BratCodec = lairs.codec("brat")
codec = ConlluCodec()
```

An unknown name raises `UnknownAdapterError`, listing the available codecs.

## The `CorpusFragment` pivot

A codec decodes into and encodes from a `CorpusFragment`: a didactic model
holding a batch of `FragmentRecord` entries. Each `FragmentRecord` carries its
`local_id`, its collection `nsid`, and the record value as a JSON string, so a
fragment is independent of any one generated namespace module and round-trips
losslessly.

```python
from lairs.integrations.codecs import CorpusFragment, FragmentRecord

fragment = codec.decode(conllu_text)
fragment.source                          # "conllu"
for record in fragment.records:
    print(record.local_id, record.nsid)  # "expression" "pub.layers.expression", ...
```

`decode` accepts `str` or `bytes` and an optional `into` fragment to extend with
the decoded records. `encode` takes an iterable of `FragmentRecord` and returns
the external representation.

## CoNLL-U

`ConlluCodec` maps Universal Dependencies CoNLL-U onto Layers:

- the `FORM` column becomes a `Token`, and a sentence's tokens become a
  `Tokenization` inside one `Segmentation` record.
- `UPOS`, `XPOS`, and `LEMMA` become token-tag `AnnotationLayer` records anchored
  by token index, with `FEATS` carried as per-annotation features.
- `HEAD`/`DEPREL` become a relation (dependency) layer, each arc carrying a
  `headIndex` (`-1` at the root) and a `targetIndex`.

```python
codec = lairs.codec("conllu")()
fragment = codec.decode(conllu_text)     # expression, segmentation, tag and dep layers
restored = codec.encode(fragment.records)
```

`ConlluCodec.decode` and `.encode` require the optional `conllu` library, from
the `lairs[conllu]` extra. It is imported lazily inside the methods, so importing
the module never pulls the dependency in. Calling `decode`/`encode` without it
raises `ModuleNotFoundError` with an install hint.

The parse used by the structural path is standard-library only. The dependency-
free path is `ConlluIso`, an `Iso` between a parsed sentence and a fragment that
operates over parsed structures and so needs no extra:

```python
from lairs.integrations.codecs.conllu import ConlluIso

iso = ConlluIso()
fragment = iso.forward(parsed_sentence)
sentence = iso.backward(fragment)        # backward(forward(x)) == x on the subset
```

## brat

`BratCodec` parses brat standoff directly, with no third-party dependency even
when the `lairs[brat]` extra is declared. The `.ann` lines it understands:

- `T` text-bound entities (`START`/`END` are UTF-8 byte offsets), which become a
  span layer anchored by a `Span`.
- `R` binary relations, which become a relation layer.
- `A` attributes on an entity, carried as annotation features.

The `.txt` and `.ann` halves are combined into one source string separated by a
sentinel line, so one `decode`/`encode` pair round-trips both halves.

```python
codec = lairs.codec("brat")()
source = txt + "\n===ANN===\n" + ann
fragment = codec.decode(source)          # expression, span layer, relation layer
combined = codec.encode(fragment.records)
```

Because brat is plain text, the whole codec works without any extra installed.

## Round-trip laws

Each codec ships an `Iso` whose round-trip law fixtures verify
`backward(forward(x)) == x` on the supported subset. The CoNLL-U subset is one
tokenisation with `UPOS`/`XPOS`/lemma tags, morphological features, and a
projective dependency tree. The brat subset is text-bound entities, binary
relations, and attributes. `canonical_standoff` returns the canonical,
round-trippable form (entity tags `T1..Tn`, relation tags `R1..Rn`, attribute
tags `A1..An`, attributes grouped under their target) that the fixtures sample
from.

## Extras at a glance

| Codec | Extra | Works without the extra |
|---|---|---|
| `conllu` | `lairs[conllu]` (the `conllu` library) | `ConlluIso` only. `ConlluCodec.decode`/`.encode` raise `ModuleNotFoundError` |
| `brat` | none required | the full codec |

## See also

- [Dataset API](dataset-api.md) for working with the records a codec produces.
- [Authoring](authoring.md) for building records and layers directly.
- [Knowledge bases](knowledge-bases.md) for grounding decoded labels.
