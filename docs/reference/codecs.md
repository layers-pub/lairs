# Format codecs

This package defines the shared corpus-fragment models and the CoNLL-U
(lossy and full-fidelity) and brat codecs, which bind to the [``Codec``](ports.md) port. A codec
decodes an external format into a ``CorpusFragment`` of records and encodes
records back. For usage, see [Guides > Format codecs](../guide/codecs.md).

## Fragment models

::: lairs.integrations.codecs.CorpusFragment

::: lairs.integrations.codecs.FragmentRecord

## CoNLL-U

::: lairs.integrations.codecs.conllu

## CoNLL-U, full fidelity

::: lairs.integrations.codecs.conllu_ud

## brat

::: lairs.integrations.codecs.brat
