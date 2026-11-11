"""Full-fidelity CoNLL-U codec for Universal Dependencies.

:class:`UdConlluCodec` (registered as ``conllu-ud``) converts between CoNLL-U
text and Layers records through :mod:`lairs.conllu`: the exact text parser,
and the one projection the Layers UD importer's published shape is defined
by. Decoding covers every column of every row (words, multiword ranges, and
empty nodes, DEPS and MISC included), all sentence comments in order, and the
``# newdoc``/``# newpar`` structure. The records are in the shape the Layers
UD importer publishes, documented in :mod:`lairs.conllu.projection`, so for
well-formed input ``encode(decode(text).records) == text`` byte for byte (up
to the framing normalisation :mod:`lairs.conllu.text` documents).

Each decoded :class:`~lairs.integrations.codecs.FragmentRecord` carries the
record's AT-URI as its ``local_id``, so a fragment is directly a record
mapping that :func:`lairs.conllu.sentences` reads.

:class:`UdConlluIso` is the single-sentence :class:`~didactic.api.Iso` between
a :class:`~lairs.conllu.model.ConlluSentence` and its fragment.

The lossy :class:`~lairs.integrations.codecs.conllu.ConlluCodec` (``conllu``)
is unchanged; use this codec when every column must survive.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, override

import didactic.api as dx

from lairs.conllu.model import ConlluSentence
from lairs.conllu.projection import EXPRESSION_NSID, Projector
from lairs.conllu.reader import sentences_from_json
from lairs.conllu.text import parse, serialize
from lairs.integrations.codecs import CorpusFragment, FragmentRecord

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from datetime import datetime

    from lairs.conllu.projection import JsonObject, OntologyResolver, RecordNaming

__all__ = ["UdConlluCodec", "UdConlluIso"]

# the codec's registered name.
_NAME = "conllu-ud"


class UdConlluCodec:
    """A lossless CoNLL-U codec bound to the Codec port.

    Parameters
    ----------
    naming : lairs.conllu.projection.RecordNaming or None, optional
        Names the records; :class:`~lairs.conllu.projection.LocalNaming` by
        default.
    ontology : lairs.conllu.projection.OntologyResolver or None, optional
        Supplies ontology references; none by default.
    created_at : datetime.datetime or None, optional
        The ``createdAt`` of every record (the Unix epoch by default).
    languages : collections.abc.Iterable of str, optional
        The BCP-47 tags stamped on expressions.
    corpus_ref : str or None, optional
        When set, each sentence also gets a membership in this corpus.
    split : str or None, optional
        The split of those memberships.
    """

    name = _NAME

    def __init__(  # noqa: PLR0913  (the projection seams, one keyword each)
        self,
        *,
        naming: RecordNaming | None = None,
        ontology: OntologyResolver | None = None,
        created_at: datetime | None = None,
        languages: Iterable[str] = (),
        corpus_ref: str | None = None,
        split: str | None = None,
    ) -> None:
        self._naming = naming
        self._ontology = ontology
        self._created_at = created_at
        self._languages = tuple(languages)
        self._corpus_ref = corpus_ref
        self._split = split

    def projector(self) -> Projector:
        """Return a fresh projector configured like this codec.

        Returns
        -------
        lairs.conllu.projection.Projector
            A projector with no document context yet.
        """
        if self._created_at is None:
            return Projector(
                naming=self._naming,
                ontology=self._ontology,
                languages=self._languages,
                corpus_ref=self._corpus_ref,
                split=self._split,
            )
        return Projector(
            naming=self._naming,
            ontology=self._ontology,
            created_at=self._created_at,
            languages=self._languages,
            corpus_ref=self._corpus_ref,
            split=self._split,
        )

    def decode(
        self,
        src: str | bytes,
        *,
        into: CorpusFragment | None = None,
    ) -> CorpusFragment:
        """Decode CoNLL-U text into a fragment of Layers records.

        Parameters
        ----------
        src : str or bytes
            The CoNLL-U text (bytes are read as UTF-8).
        into : lairs.integrations.codecs.CorpusFragment or None, optional
            A fragment to extend; sentence ordinals continue after its
            sentences, so default names never collide.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The records of every sentence.

        Raises
        ------
        lairs.conllu.text.ConlluSyntaxError
            When the text is malformed.
        """
        text = src.decode("utf-8") if isinstance(src, bytes) else src
        return self.decode_sentences(parse(text), into=into)

    def decode_sentences(
        self,
        sentences: Iterable[ConlluSentence],
        *,
        into: CorpusFragment | None = None,
    ) -> CorpusFragment:
        """Project typed sentences into a fragment of Layers records.

        Parameters
        ----------
        sentences : collections.abc.Iterable of ConlluSentence
            The sentences, in order.
        into : lairs.integrations.codecs.CorpusFragment or None, optional
            A fragment to extend.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The records of every sentence.
        """
        records = list(into.records) if into is not None else []
        start = sum(
            1
            for record in records
            if record.nsid == EXPRESSION_NSID
            and (value := _value(record)) is not None
            and value.get("kind") == "sentence"
        )
        records.extend(
            FragmentRecord(
                local_id=record.uri,
                nsid=record.nsid,
                value_json=record.value_json,
            )
            for record in self.projector().project(sentences, start=start)
        )
        return CorpusFragment(records=tuple(records), source=self.name)

    def encode(self, records: Iterable[FragmentRecord]) -> str:
        """Encode fragment records back into CoNLL-U text.

        Parameters
        ----------
        records : collections.abc.Iterable of FragmentRecord
            The records, as :meth:`decode` produced them (or any records of the
            same shape whose ``local_id`` is the record's AT-URI).

        Returns
        -------
        str
            The CoNLL-U text.
        """
        return serialize(self.sentences(records))

    def sentences(self, records: Iterable[FragmentRecord]) -> Iterator[ConlluSentence]:
        """Read typed sentences out of fragment records.

        Parameters
        ----------
        records : collections.abc.Iterable of FragmentRecord
            The records.

        Returns
        -------
        collections.abc.Iterator of ConlluSentence
            The sentences, in membership order or else record order.
        """
        return sentences_from_json(
            (record.local_id, record.nsid, value)
            for record, value in ((r, _value(r)) for r in records)
            if value is not None
        )

    @staticmethod
    def encode_sentences(sentences: Iterable[ConlluSentence]) -> str:
        """Serialise typed sentences to CoNLL-U text.

        Parameters
        ----------
        sentences : collections.abc.Iterable of ConlluSentence
            The sentences, for instance from :func:`lairs.conllu.sentences`.

        Returns
        -------
        str
            The CoNLL-U text.
        """
        return serialize(sentences)


def _value(record: FragmentRecord) -> JsonObject | None:
    """Return a fragment record's value as a JSON object, if it is one."""
    value = json.loads(record.value_json)
    return value if isinstance(value, dict) else None


class UdConlluIso(dx.Iso[ConlluSentence, CorpusFragment]):
    """An :class:`~didactic.api.Iso` between one sentence and its fragment.

    ``backward(forward(sentence)) == sentence`` for every well-formed
    sentence, since the record shape holds every column and comment.
    """

    @override
    def forward(self, a: ConlluSentence, /) -> CorpusFragment:
        """Project one sentence into a fragment.

        Parameters
        ----------
        a : ConlluSentence
            The sentence.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            Its records.
        """
        return UdConlluCodec().decode_sentences((a,))

    @override
    def backward(self, b: CorpusFragment, /) -> ConlluSentence:
        """Rebuild the first sentence of a fragment.

        Parameters
        ----------
        b : lairs.integrations.codecs.CorpusFragment
            The fragment.

        Returns
        -------
        ConlluSentence
            The sentence.

        Raises
        ------
        ValueError
            When the fragment holds no sentence.
        """
        for sentence in UdConlluCodec().sentences(b.records):
            return sentence
        message = "the fragment holds no sentence"
        raise ValueError(message)
