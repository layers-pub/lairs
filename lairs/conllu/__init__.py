"""Typed, exact CoNLL-U, and its projection onto Layers records.

The package has four parts:

- :mod:`lairs.conllu.model`: the typed :class:`ConlluSentence` and
  :class:`ConlluRow` models (words, multiword ranges, and empty nodes) with
  their :class:`RowId`, :class:`Feat`, :class:`Dep`, and :class:`MiscItem`
  values;
- :mod:`lairs.conllu.text`: streaming :func:`parse` and exact
  :func:`serialize`;
- :mod:`lairs.conllu.projection`: the one mapping between sentences and
  ``pub.layers.*`` records, with the lossless carriers;
- :mod:`lairs.conllu.reader`: :func:`sentences`, which reads sentences back
  out of a loaded corpus or a raw record mapping.

Typical use::

    for sentence in lairs.conllu.sentences(corpus):
        sentence.sent_id, sentence.comments
        for row in sentence.rows:
            row.id, row.form, row.lemma, row.upos, row.xpos, row.feats
            row.head, row.deprel, row.deps, row.misc
"""

from __future__ import annotations

from lairs.conllu.model import (
    Comment,
    ConlluRow,
    ConlluSentence,
    Dep,
    Feat,
    MiscItem,
    RowId,
    RowKind,
)
from lairs.conllu.projection import (
    FeatResolution,
    LocalNaming,
    NoOntology,
    OntologyResolver,
    ProjectedRecord,
    Projector,
    RecordNaming,
    sentence_from_json,
    sentence_from_records,
)
from lairs.conllu.reader import sentences, sentences_from_json
from lairs.conllu.text import ConlluSyntaxError, dump, parse, serialize

__all__ = [
    "Comment",
    "ConlluRow",
    "ConlluSentence",
    "ConlluSyntaxError",
    "Dep",
    "Feat",
    "FeatResolution",
    "LocalNaming",
    "MiscItem",
    "NoOntology",
    "OntologyResolver",
    "ProjectedRecord",
    "Projector",
    "RecordNaming",
    "RowId",
    "RowKind",
    "dump",
    "parse",
    "sentence_from_json",
    "sentence_from_records",
    "sentences",
    "sentences_from_json",
    "serialize",
]
