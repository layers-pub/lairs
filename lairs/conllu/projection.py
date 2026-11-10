"""The projection between CoNLL-U sentences and Layers records.

This module is the single place the CoNLL-U to ``pub.layers.*`` mapping lives.
:class:`Projector` maps sentences forward to records, and
:func:`sentence_from_json` maps one sentence's records back. The local codec
(:class:`~lairs.integrations.codecs.conllu_ud.UdConlluCodec`) and the reader
(:func:`lairs.conllu.sentences`) both go through it, so a corpus encoded
locally and the same corpus as published by the Layers UD importer have one
shape.

The published shape
-------------------
Per sentence, the forward projection emits what the importer publishes:

- a sentence ``Expression`` (``kind="sentence"``, ``id`` = ``sent_id``, the
  sentence text, ``parentRef`` to the enclosing paragraph or document, and the
  non-structural ``key = value`` comments as sorted ``features``), plus a
  document or paragraph ``Expression`` the first time a ``# newdoc`` or
  ``# newpar`` opens one;
- a ``Segmentation`` holding a surface tokenization (a multiword token is one
  token) and a syntactic-word tokenization, with UTF-8 byte spans into the
  sentence text (the words of a multiword token share its span);
- when the sentence has a multiword token, an ``Alignment``
  (``tokenization-to-tokenization``, ``word-to-word``) from surface tokens to
  words, whose links carry the range row's MISC and ``feats:<F>`` entries;
- token-tag layers on the words: ``pos`` (UPOS), ``xpos``, ``lemma``, and
  ``morph`` (one annotation per ``Feature=Value``);
- a ``dependency`` relation layer (``headIndex`` 0-based, ``-1`` at the root,
  with ``ud_relation``, ``ud_subtype``, and the word's sorted MISC pairs);
- when DEPS is present, a second ``Segmentation`` with an enhanced
  tokenization (the words, then the empty nodes) and an
  ``enhanced-dependency`` layer with one annotation per arc;
- when a corpus reference is configured, a ``Membership`` with the ordinal and
  split.

That shape loses information: MISC order, bare items, and ``SpaceAfter``;
comment order and comments without a value; layered feature names and the
grouping of multi-valued features; the LEMMA, UPOS, XPOS, FEATS, and MISC of
empty nodes; the MISC of words with no HEAD; and anything a non-canonical file
does differently.

The lossless carriers
---------------------
On top of the published shape, the forward projection adds carriers for
exactly what the shape loses. They never change the meaning of a published
field: they are extra ``features`` entries whose keys start with ``conllu:``,
and one extra annotation layer with its own subkind.

On the sentence ``Expression``'s ``features``, after the published entries:

- ``conllu:scheme`` = ``1``: the sentence carries the carriers of this scheme.
- ``conllu:comment``: one entry per comment line, in order, holding the line
  after its ``#`` verbatim; or ``conllu:comment-ref`` = ``sent_id`` or
  ``text`` in its place when the line is exactly ``# sent_id = <id>`` or
  ``# text = <text>`` for the expression's own ``id`` or ``text``.
- ``conllu:order``: the row ids in source order, space-separated, present only
  when the rows are not in canonical order (each range just before its first
  word, each empty node ``n.m`` just after word ``n``).
- ``conllu:rows``: the number of row annotations in the carrier layer, present
  only when it is not zero.

A carrier layer (``kind="token-tag"``, ``subkind="conllu"``) holds one
annotation per row whose columns the published shape does not restore
exactly. Its ``label`` is the row id (``3``, ``1-2``, ``3.1``); a word row also
carries ``tokenIndex`` and a token anchor. Its features are
``conllu:<column>`` = the column's exact text for each such column
(``form``, ``lemma``, ``upos``, ``xpos``, ``feats``, ``head``, ``deprel``,
``deps``, ``misc``), or ``conllu:drop`` = ``true`` for a row the published
shape implies but the source does not have.

The forward projection decides which rows need a carrier by running the
inverse over its own published-shape output and comparing it with the source,
so the carriers are minimal and the round trip is exact by construction. A
carrier value longer than the 4096-byte ``Feature.value`` limit is split at
character boundaries, and each further piece follows as a ``conllu:more``
entry appended to the entry before it.

The inverse
-----------
:func:`sentence_from_json` reads one sentence's records as JSON (wire JSON with
``$type`` keys and explicit nulls, or model-dumped JSON; an absent key and a
null are the same) and rebuilds the sentence. With carriers the result is
exact. Without them (records as the importer currently publishes them) it
reconstructs what it can: MISC from the sorted pairs plus ``SpaceAfter=No``
from adjacent byte spans, FEATS regrouped from the morph annotations with
``ud_feats_original`` undoing normalisation, empty nodes from
``ud_empty_node`` and the enhanced tokenization, multiword ranges from the
alignment or from shared spans, and comments from the expression's fields.
The result's :attr:`~lairs.conllu.model.ConlluSentence.lossy` then names the
fields that were reconstructed: ``comments``, ``misc``, ``feats``,
``empty_nodes``, ``multiword_tokens``, and ``deps``, as they apply, plus
``carriers`` when a sentence declares carriers that are missing.

Seams for other producers
-------------------------
The naming of records, uuids, and references (:class:`RecordNaming`), the
ontology references and FEATS normalisation (:class:`OntologyResolver`), the
``createdAt`` stamp, languages, source method, corpus reference, and split are
all parameters of :class:`Projector`, with neutral defaults. A producer such as
the Layers UD importer supplies its own naming and an ontology resolver backed
by its registry, and gets the same records it builds today plus the carriers.
"""

from __future__ import annotations

import functools
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import didactic.api as dx

from lairs.conllu.model import (
    COLUMNS,
    DEPREL,
    DEPS,
    EMPTY,
    FEATS,
    FORM,
    HEAD,
    ID,
    LEMMA,
    MISC,
    UPOS,
    XPOS,
    ConlluSentence,
    split_items,
)
from lairs.records._generated.alignment import Alignment
from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.corpus import Membership
from lairs.records._generated.defs import Feature
from lairs.records._generated.expression import Expression
from lairs.records._generated.segmentation import Segmentation

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from lairs._types import JsonValue

__all__ = [
    "ALIGNMENT_NSID",
    "ANNOTATION_NSID",
    "CARRIER_PREFIX",
    "CARRIER_SCHEME",
    "CARRIER_SUBKIND",
    "EXPRESSION_NSID",
    "MEMBERSHIP_NSID",
    "SEGMENTATION_NSID",
    "FeatResolution",
    "JsonObject",
    "LayersRecord",
    "LocalNaming",
    "NoOntology",
    "OntologyResolver",
    "ProjectedRecord",
    "Projector",
    "RecordNaming",
    "sentence_from_json",
    "sentence_from_records",
]

type JsonObject = dict[str, JsonValue]
"""One record value (or nested object) as JSON."""

type LayersRecord = Expression | Segmentation | Alignment | AnnotationLayer | Membership
"""A Layers record the projection produces or reads."""

# the collection nsids of the records a sentence projects to.
EXPRESSION_NSID = "pub.layers.expression.expression"
SEGMENTATION_NSID = "pub.layers.segmentation.segmentation"
ANNOTATION_NSID = "pub.layers.annotation.annotationLayer"
ALIGNMENT_NSID = "pub.layers.alignment.alignment"
MEMBERSHIP_NSID = "pub.layers.corpus.membership"

# the carrier scheme: the key prefix, the version, and the carrier subkind.
CARRIER_PREFIX = "conllu:"
CARRIER_SCHEME = "1"
CARRIER_SUBKIND = "conllu"

# the carrier feature keys.
_K_SCHEME = "conllu:scheme"
_K_COMMENT = "conllu:comment"
_K_COMMENT_REF = "conllu:comment-ref"
_K_ORDER = "conllu:order"
_K_ROWS = "conllu:rows"
_K_MORE = "conllu:more"
_K_DROP = "conllu:drop"

# the carrier key of each column after the id, by column position.
_COLUMN_KEYS = {
    FORM: "conllu:form",
    LEMMA: "conllu:lemma",
    UPOS: "conllu:upos",
    XPOS: "conllu:xpos",
    FEATS: "conllu:feats",
    HEAD: "conllu:head",
    DEPREL: "conllu:deprel",
    DEPS: "conllu:deps",
    MISC: "conllu:misc",
}
_KEY_COLUMNS = {key: column for column, key in _COLUMN_KEYS.items()}

# the maximum utf-8 length of a Feature.value.
_MAX_VALUE_BYTES = 4096

# the published feature keys of dependency and enhanced annotations.
_UD_RELATION = "ud_relation"
_UD_SUBTYPE = "ud_subtype"
_UD_EMPTY_NODE = "ud_empty_node"
_UD_FEATS_ORIGINAL = "ud_feats_original"
_IS_ENHANCED = "isEnhanced"
_FEATS_LINK_PREFIX = "feats:"
_SPACE_AFTER = "SpaceAfter"

# the published layer vocabulary.
_FORMALISM = "universal-dependencies"
_TOKEN_TAG = "token-tag"
_RELATION = "relation"
_SUBKIND_POS = "pos"
_SUBKIND_XPOS = "xpos"
_SUBKIND_LEMMA = "lemma"
_SUBKIND_MORPH = "morph"
_SUBKIND_DEPENDENCY = "dependency"
_SUBKIND_ENHANCED = "enhanced-dependency"
_MULTIWORD_LABEL = "multiword-token"
_ONE_TO_ONE_LABEL = "one-to-one"

# the comment keys the published expression consumes structurally.
_STRUCTURAL_KEYS = frozenset(
    {"newdoc id", "newdoc", "newpar id", "newpar", "sent_id", "text"}
)

# the head index of the dependency root.
_ROOT = -1

# the lossy field names a reconstructed sentence may report.
LOSSY_COMMENTS = "comments"
LOSSY_MISC = "misc"
LOSSY_FEATS = "feats"
LOSSY_EMPTY_NODES = "empty_nodes"
LOSSY_MULTIWORD = "multiword_tokens"
LOSSY_DEPS = "deps"
LOSSY_CARRIERS = "carriers"

# the default createdAt stamp of projected records.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# length-preserving canonicalisation of quotes, dashes, and spaces, used to
# locate a form the declared text spells with different punctuation.
_NORMALIZE_TABLE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
        " ": " ",
        " ": " ",
        " ": " ",
    }
)


# -----------------------------------------------------------------------------
# seams
# -----------------------------------------------------------------------------


class FeatResolution(dx.Model):
    """How one FEATS ``Feature=Value`` pair is published.

    Attributes
    ----------
    feature : str
        The feature the annotation label names (after any normalisation).
    value : str
        The value the annotation label names (after any normalisation).
    type_ref : str or None
        The ``ontologyTypeRef`` of the annotation, if any.
    literal : str or None
        The literal ``value`` of the annotation (an open-class feature's value),
        if any.
    extra : tuple of Feature
        Extra annotation features, such as ``ud_feats_original`` when the pair
        was normalised.
    """

    feature: str = dx.field(description="feature named by the label")
    value: str = dx.field(description="value named by the label")
    type_ref: str | None = dx.field(default=None, description="ontologyTypeRef")
    literal: str | None = dx.field(default=None, description="literal value")
    extra: tuple[dx.Embed[Feature], ...] = dx.field(
        default=(),
        description="extra annotation features",
    )


@runtime_checkable
class OntologyResolver(Protocol):
    """Resolves UD labels to ontology references.

    The Layers UD importer references UPOS tags, dependency relations, and
    FEATS pairs into published ontologies, normalising known misspellings and
    minting language-specific values. A resolver supplies those references to
    :class:`Projector`; it may keep its own state (for example the minted
    typeDefs it must also publish). :class:`NoOntology` is the neutral default.
    """

    def ontology(self, kind: str) -> str | None:
        """Return the ``ontologyRef`` of the ``pos``, ``deprel``, or ``feats`` layer."""
        ...

    def pos_type(self, upos: str) -> str | None:
        """Return the ``ontologyTypeRef`` of a UPOS tag."""
        ...

    def deprel_type(self, deprel: str) -> str | None:
        """Return the ``ontologyTypeRef`` of a (possibly subtyped) relation."""
        ...

    def feat(self, feature: str, value: str) -> FeatResolution:
        """Return how one ``Feature=Value`` pair (layer stripped) is published."""
        ...


class NoOntology:
    """The neutral resolver: no ontology references and no normalisation."""

    def ontology(self, kind: str) -> str | None:  # noqa: ARG002, PLR6301
        """Return ``None``: the layer references no ontology."""
        return None

    def pos_type(self, upos: str) -> str | None:  # noqa: ARG002, PLR6301
        """Return ``None``: the tag references no typeDef."""
        return None

    def deprel_type(self, deprel: str) -> str | None:  # noqa: ARG002, PLR6301
        """Return ``None``: the relation references no typeDef."""
        return None

    def feat(self, feature: str, value: str) -> FeatResolution:  # noqa: PLR6301
        """Return the pair unchanged, with no references."""
        return _plain_feat(feature, value)


@functools.lru_cache(maxsize=1 << 14)
def _plain_feat(feature: str, value: str) -> FeatResolution:
    """Return the interned unresolved resolution of a pair."""
    return FeatResolution(feature=feature, value=value)


@runtime_checkable
class RecordNaming(Protocol):
    """Names projected records, tokenizations, and references.

    ``role`` is one of ``expr``, ``seg``, ``seg-enhanced``, ``align``,
    ``upos``, ``xpos``, ``lemma``, ``morph``, ``deps``, ``edeps``, ``conllu``,
    and ``mem`` for records, and ``surface``, ``words``, and ``enhanced`` for
    tokenization uuids. These are the suffixes the Layers UD importer uses, so
    its scheme is ``f"{stem}/{sent_id}/{role}"`` with references
    ``f"at://local/{local_id}"``.
    """

    def local_id(self, role: str, sentence_id: str, ordinal: int) -> str:
        """Return the local id (record key) of one of a sentence's records."""
        ...

    def uuid(self, role: str, sentence_id: str, ordinal: int) -> str:
        """Return the uuid of one of a sentence's tokenizations."""
        ...

    def unit_local_id(self, kind: str, unit_id: str, index: int) -> str:
        """Return the local id of a ``document`` or ``paragraph`` expression."""
        ...

    def reference(self, nsid: str, local_id: str) -> str:
        """Return the AT-URI other records use to reference a record."""
        ...


class LocalNaming:
    """The default naming: record keys and AT-URIs under ``at://local``.

    Records are keyed ``<stem>-<ordinal>-<role>`` (valid record keys whatever
    the sentence ids contain), tokenizations ``<stem>/<ordinal>/<role>``, and
    references are ``at://local/<collection>/<key>``.

    Parameters
    ----------
    stem : str, optional
        The prefix of every key.
    """

    def __init__(self, stem: str = "conllu") -> None:
        self.stem = stem

    def local_id(self, role: str, sentence_id: str, ordinal: int) -> str:  # noqa: ARG002
        """Return ``<stem>-<ordinal>-<role>``."""
        return f"{self.stem}-{ordinal}-{role}"

    def uuid(self, role: str, sentence_id: str, ordinal: int) -> str:  # noqa: ARG002
        """Return ``<stem>/<ordinal>/<role>``."""
        return f"{self.stem}/{ordinal}/{role}"

    def unit_local_id(self, kind: str, unit_id: str, index: int) -> str:  # noqa: ARG002
        """Return ``<stem>-<kind>-<index>``."""
        return f"{self.stem}-{kind}-{index}"

    def reference(self, nsid: str, local_id: str) -> str:  # noqa: PLR6301
        """Return ``at://local/<nsid>/<local_id>``."""
        return f"at://local/{nsid}/{local_id}"


class ProjectedRecord(dx.Model):
    """One record the forward projection produced.

    Attributes
    ----------
    role : str
        What the record is for the sentence (``expr``, ``seg``, ``upos``, and
        so on; ``document`` and ``paragraph`` for structure expressions).
    nsid : str
        The record's collection NSID.
    local_id : str
        The record's local id under the naming scheme.
    uri : str
        The AT-URI other records reference it by.
    value_json : str
        The record value as JSON.
    """

    role: str = dx.field(description="what the record is for the sentence")
    nsid: str = dx.field(description="collection NSID")
    local_id: str = dx.field(description="local id under the naming scheme")
    uri: str = dx.field(description="AT-URI other records reference it by")
    value_json: str = dx.field(description="record value as JSON")

    def value(self) -> JsonObject:
        """Return the record value as a JSON object."""
        value = json.loads(self.value_json)
        if not isinstance(value, dict):
            message = "projected record value is not a JSON object"
            raise TypeError(message)
        return value

    def to_model(self) -> LayersRecord:
        """Validate the value into its generated record model.

        Returns
        -------
        LayersRecord
            The typed record.

        Raises
        ------
        didactic.api.ValidationError
            When the value does not validate (it always should).
        ValueError
            When the collection is not one the projection produces.
        """
        model = _MODELS.get(self.nsid)
        if model is None:
            message = f"no record model for collection {self.nsid!r}"
            raise ValueError(message)
        return model.model_validate_json(self.value_json)


_MODELS: dict[
    str,
    type[Expression]
    | type[Segmentation]
    | type[Alignment]
    | type[AnnotationLayer]
    | type[Membership],
] = {
    EXPRESSION_NSID: Expression,
    SEGMENTATION_NSID: Segmentation,
    ALIGNMENT_NSID: Alignment,
    ANNOTATION_NSID: AnnotationLayer,
    MEMBERSHIP_NSID: Membership,
}


# -----------------------------------------------------------------------------
# column helpers shared by both directions
# -----------------------------------------------------------------------------


def _pairs(column: str) -> dict[str, str | None]:
    """Read a FEATS or MISC column as published: a last-wins key map.

    A bare item maps to ``""``; an item whose value is empty or ``_`` maps to
    ``None`` (and is not published); an item whose key is empty or ``_`` is
    skipped. This is how the importer's parser reads these columns, except
    that a value keeps any further ``=`` it contains.
    """
    pairs: dict[str, str | None] = {}
    for item in split_items(column):
        key, sep, value = item.partition("=")
        if key in {"", EMPTY}:
            continue
        if not sep:
            pairs[key] = ""
        else:
            pairs[key] = None if value in {"", EMPTY} else value
    return pairs


def _published_misc(column: str) -> list[tuple[str, str]]:
    """Return the MISC pairs the published shape carries, sorted, minus SpaceAfter."""
    return sorted(
        (key, value)
        for key, value in _pairs(column).items()
        if key != _SPACE_AFTER and value is not None
    )


def _space_after(column: str) -> bool:
    """Return whether a MISC column leaves a space after its token."""
    return _pairs(column).get(_SPACE_AFTER) != "No"


def _feature_name(name: str) -> str:
    """Strip the layer from a feature name (``Number[psor]`` to ``Number``)."""
    start = name.find("[")
    return name[:start] if start != -1 else name


def _split_deprel(deprel: str) -> tuple[str, str | None]:
    """Split a relation into its universal part and subtype."""
    universal, sep, subtype = deprel.partition(":")
    return universal, subtype if sep else None


def _render_pairs(pairs: Iterable[tuple[str, str]]) -> str:
    """Render key/value pairs as a MISC column (``""`` values as bare items)."""
    items = [key if value == "" else f"{key}={value}" for key, value in pairs]
    return "|".join(items) or EMPTY


def _row_key(row_id: str) -> tuple[int, int, int]:
    """Return the canonical sort key of a row id.

    A range sorts just before its first word and an empty node ``n.m`` just
    after word ``n``.
    """
    if "-" in row_id:
        start, _, _end = row_id.partition("-")
        return int(start), 0, 0
    if "." in row_id:
        major, _, minor = row_id.partition(".")
        return int(major), 2, int(minor)
    return int(row_id), 1, 0


def _chunks(value: str) -> list[str]:
    """Split a carrier value into pieces of at most 4096 utf-8 bytes."""
    if len(value) * 4 <= _MAX_VALUE_BYTES or (
        len(value.encode("utf-8")) <= _MAX_VALUE_BYTES
    ):
        return [value]
    pieces: list[str] = []
    piece: list[str] = []
    size = 0
    for char in value:
        width = len(char.encode("utf-8"))
        if size + width > _MAX_VALUE_BYTES:
            pieces.append("".join(piece))
            piece = []
            size = 0
        piece.append(char)
        size += width
    pieces.append("".join(piece))
    return pieces


def _carrier_entries(key: str, value: str) -> list[JsonValue]:
    """Return the feature entries of one carrier value, split when long."""
    pieces = _chunks(value)
    entries: list[JsonValue] = [{"key": key, "value": pieces[0]}]
    entries.extend({"key": _K_MORE, "value": piece} for piece in pieces[1:])
    return entries


def _canonical(value: str) -> str:
    """Canonicalise quotes, dashes, and spaces, one character for one."""
    return value.translate(_NORMALIZE_TABLE)


def _surface_spans(forms: Sequence[str], text: str) -> list[tuple[int, int] | None]:
    """Locate each surface form in the text and return its utf-8 byte span.

    Forms are searched from a moving cursor, retrying on canonicalised quotes,
    dashes, and spaces; a form that cannot be located gets no span.
    """
    spans: list[tuple[int, int] | None] = []
    canonical_text = _canonical(text)
    byte_cursor = 0
    char_cursor = 0
    for form in forms:
        located = text.find(form, char_cursor)
        if located == -1:
            located = canonical_text.find(_canonical(form), char_cursor)
        if located == -1:
            spans.append(None)
            continue
        byte_cursor += len(text[char_cursor:located].encode("utf-8"))
        start = byte_cursor
        end = start + len(text[located : located + len(form)].encode("utf-8"))
        spans.append((start, end))
        byte_cursor = end
        char_cursor = located + len(form)
    return spans


def _comment_metadata(comment_lines: Sequence[str]) -> dict[str, str | None]:
    """Read comment lines as the importer does: a last-wins key/value map.

    ``# newdoc`` and ``# newpar`` keep a ``None`` value; other comments need a
    non-empty key and value.
    """
    metadata: dict[str, str | None] = {}
    for line in comment_lines:
        key, sep, value = line.strip()[1:].partition("=")
        key = key.strip()
        stripped = value.strip() if sep else None
        if key in {"newdoc", "newpar"}:
            metadata[key] = stripped
        elif key and stripped:
            metadata[key] = stripped
    return metadata


def _unit_id(metadata: dict[str, str | None], marker: str) -> str | None:
    """Return the id of a ``# newdoc`` or ``# newpar`` marker, if present."""
    keyed = metadata.get(f"{marker} id")
    if keyed:
        return keyed
    if marker in metadata:
        sent_id = metadata.get("sent_id")
        return f"{marker}:{sent_id or 'anon'}"
    return None


# -----------------------------------------------------------------------------
# forward
# -----------------------------------------------------------------------------


class _Units:
    """The document and paragraph context of a run of sentences."""

    def __init__(self) -> None:
        self.document: str | None = None
        self.paragraph: str | None = None
        self.seen: dict[tuple[str, str], str] = {}


class Projector:
    """Projects CoNLL-U sentences to Layers records.

    Parameters
    ----------
    naming : RecordNaming or None, optional
        Names records, uuids, and references; :class:`LocalNaming` by default.
    ontology : OntologyResolver or None, optional
        Supplies ontology references; :class:`NoOntology` by default.
    created_at : datetime.datetime, optional
        The ``createdAt`` of every record (the Unix epoch by default, so a
        projection is deterministic).
    languages : collections.abc.Iterable of str, optional
        The BCP-47 tags stamped on expressions.
    source_method : str or None, optional
        The ``sourceMethod`` of every layer (``converted`` by default).
    corpus_ref : str or None, optional
        When set, every sentence also gets a ``Membership`` in this corpus.
    split : str or None, optional
        The ``split`` of those memberships.
    tool : str, optional
        The ``metadata.tool`` of the multiword-token alignment.
    carriers : bool, optional
        Whether to add the lossless carriers (true by default). Without them
        the output is exactly the published shape.
    """

    def __init__(  # noqa: PLR0913  (each projection seam is one keyword)
        self,
        *,
        naming: RecordNaming | None = None,
        ontology: OntologyResolver | None = None,
        created_at: datetime = _EPOCH,
        languages: Iterable[str] = (),
        source_method: str | None = "converted",
        corpus_ref: str | None = None,
        split: str | None = None,
        tool: str = "lairs conllu-ud",
        carriers: bool = True,
    ) -> None:
        self.naming: RecordNaming = naming if naming is not None else LocalNaming()
        self.ontology: OntologyResolver = (
            ontology if ontology is not None else NoOntology()
        )
        self.created_at = created_at.isoformat()
        self.languages = tuple(languages)
        self.source_method = source_method
        self.corpus_ref = corpus_ref
        self.split = split
        self.tool = tool
        self.carriers = carriers
        self._units = _Units()

    def project(self, sentences: Iterable[ConlluSentence]) -> Iterator[ProjectedRecord]:
        """Project a run of sentences, tracking documents and paragraphs.

        Ordinals count from 0 in iteration order. A document or paragraph
        expression is emitted the first time a sentence opens it.

        Parameters
        ----------
        sentences : collections.abc.Iterable of ConlluSentence
            The sentences of one document or treebank file, in order.

        Yields
        ------
        ProjectedRecord
            The records, sentence by sentence.
        """
        for ordinal, sentence in enumerate(sentences):
            yield from self.project_sentence(sentence, ordinal)

    def project_sentence(
        self,
        sentence: ConlluSentence,
        ordinal: int,
    ) -> list[ProjectedRecord]:
        """Project one sentence, in the document context of the earlier ones.

        Parameters
        ----------
        sentence : ConlluSentence
            The sentence.
        ordinal : int
            Its 0-based position in the corpus.

        Returns
        -------
        list of ProjectedRecord
            Any newly opened document or paragraph expression, then the
            sentence's expression, segmentations, alignment, layers, and
            membership.
        """
        out: list[ProjectedRecord] = []
        metadata = _comment_metadata(sentence.comment_lines)
        parent = self._open_units(metadata, out)
        out.extend(self._sentence_records(sentence, ordinal, metadata, parent))
        return out

    def _open_units(
        self,
        metadata: dict[str, str | None],
        out: list[ProjectedRecord],
    ) -> str | None:
        """Open any new document or paragraph and return the sentence's parent."""
        units = self._units
        doc_id = _unit_id(metadata, "newdoc")
        if doc_id is not None:
            units.document = self._unit("document", doc_id, None, out)
            units.paragraph = None
        par_id = _unit_id(metadata, "newpar")
        if par_id is not None:
            units.paragraph = self._unit("paragraph", par_id, units.document, out)
        return units.paragraph or units.document

    def _unit(
        self,
        kind: str,
        unit_id: str,
        parent: str | None,
        out: list[ProjectedRecord],
    ) -> str:
        """Return the reference of a structure expression, emitting it once."""
        seen = self._units.seen
        known = seen.get((kind, unit_id))
        if known is not None:
            return known
        local_id = self.naming.unit_local_id(kind, unit_id, len(seen))
        uri = self.naming.reference(EXPRESSION_NSID, local_id)
        seen[kind, unit_id] = uri
        value: JsonObject = {"id": unit_id, "kind": kind}
        if self.languages:
            value["languages"] = list(self.languages)
        if parent is not None:
            value["parentRef"] = parent
        value["createdAt"] = self.created_at
        out.append(_record(kind, EXPRESSION_NSID, local_id, uri, value))
        return uri

    def _sentence_records(
        self,
        sentence: ConlluSentence,
        ordinal: int,
        metadata: dict[str, str | None],
        parent: str | None,
    ) -> list[ProjectedRecord]:
        """Build one sentence's records: the published shape plus carriers."""
        shape = _Shape(self, sentence, ordinal, metadata, parent)
        records = shape.published()
        if not self.carriers:
            return records
        predicted = _predict(shape.json_records())
        carrier_rows = _row_carriers(predicted.columns, shape.rows)
        order = [row[ID] for row in shape.rows]
        canonical = sorted(order, key=_row_key)
        entries = shape.comment_carriers()
        if order != canonical:
            entries.extend(_carrier_entries(_K_ORDER, " ".join(order)))
        if carrier_rows:
            entries.append({"key": _K_ROWS, "value": str(len(carrier_rows))})
            records.append(shape.carrier_layer(carrier_rows))
        expression = records[0].value()
        features = expression.get("features")
        published = features.get("entries") if isinstance(features, dict) else None
        merged: list[JsonValue] = list(published) if isinstance(published, list) else []
        merged.append({"key": _K_SCHEME, "value": CARRIER_SCHEME})
        merged.extend(entries)
        expression["features"] = {"entries": merged}
        records[0] = records[0].with_(value_json=json.dumps(expression))
        return records


def _record(
    role: str,
    nsid: str,
    local_id: str,
    uri: str,
    value: JsonObject,
) -> ProjectedRecord:
    """Build a projected record from its JSON value."""
    return ProjectedRecord(
        role=role,
        nsid=nsid,
        local_id=local_id,
        uri=uri,
        value_json=json.dumps(value, ensure_ascii=False),
    )


def _anchor(index: int, uuid: str) -> JsonObject:
    """Return the token anchor of an annotation."""
    return {"tokenRef": {"tokenIndex": index, "tokenizationId": {"value": uuid}}}


def _feature_map(entries: Sequence[tuple[str, str]]) -> JsonObject | None:
    """Return a feature map of key/value pairs, or ``None`` when empty."""
    if not entries:
        return None
    return {"entries": [{"key": key, "value": value} for key, value in entries]}


def _drop_none(value: JsonObject) -> JsonObject:
    """Return ``value`` without its ``None`` entries."""
    return {key: item for key, item in value.items() if item is not None}


class _Shape:
    """The published shape of one sentence, built once and read by both halves."""

    def __init__(
        self,
        projector: Projector,
        sentence: ConlluSentence,
        ordinal: int,
        metadata: dict[str, str | None],
        parent: str | None,
    ) -> None:
        self.p = projector
        self.ordinal = ordinal
        self.metadata = metadata
        self.parent = parent
        self.comment_lines = sentence.comment_lines
        self.rows = [tuple(line.split("\t")) for line in sentence.row_lines]
        self.words = [row for row in self.rows if row[ID].isdigit()]
        self.empties = [row for row in self.rows if "." in row[ID]]
        self.ranges = {
            int(row[ID].partition("-")[0]): row for row in self.rows if "-" in row[ID]
        }
        sent_id = metadata.get("sent_id")
        self.sid = sent_id or f"s{ordinal}"
        naming = projector.naming
        self.uuid_surface = naming.uuid("surface", self.sid, ordinal)
        self.uuid_words = naming.uuid("words", self.sid, ordinal)
        self.uuid_enhanced = naming.uuid("enhanced", self.sid, ordinal)
        self.expr_local = naming.local_id("expr", self.sid, ordinal)
        self.expr_ref = naming.reference(EXPRESSION_NSID, self.expr_local)
        self._units()
        declared = metadata.get("text")
        self.text = declared or self._joined()
        spans = _surface_spans([unit[0] for unit in self.units], self.text)
        self.unit_spans = spans
        self.word_spans: dict[int, tuple[int, int] | None] = {}
        for (_form, word_ids, _misc, _feats), span in zip(self.units, spans, strict=True):
            for word_id in word_ids:
                self.word_spans[word_id] = span
        self._json: list[tuple[str, JsonObject]] = []

    def _units(self) -> None:
        """Compute the surface units: (form, word ids, misc, feats) in order."""
        words = {int(row[ID]): row for row in self.words}
        self.units: list[tuple[str, tuple[int, ...], str, str]] = []
        if not words:
            return
        cursor = min(words)
        last = max(words)
        while cursor <= last:
            if cursor not in words:
                cursor += 1
                continue
            mwt = self.ranges.get(cursor)
            if mwt is not None:
                end = int(mwt[ID].partition("-")[2])
                covered = tuple(i for i in range(cursor, end + 1) if i in words)
                self.units.append((mwt[FORM], covered, mwt[MISC], mwt[FEATS]))
                cursor = end + 1
            else:
                row = words[cursor]
                self.units.append((row[FORM], (cursor,), row[MISC], EMPTY))
                cursor += 1

    def _joined(self) -> str:
        """Join the surface forms honouring ``SpaceAfter``."""
        parts: list[str] = []
        for index, (form, _ids, misc, _feats) in enumerate(self.units):
            parts.append(form)
            if _space_after(misc) and index < len(self.units) - 1:
                parts.append(" ")
        return "".join(parts)

    def _local(self, role: str) -> str:
        """Return the local id of one of the sentence's records."""
        return self.p.naming.local_id(role, self.sid, self.ordinal)

    def _emit(self, role: str, nsid: str, value: JsonObject) -> ProjectedRecord:
        """Record one JSON value and wrap it as a projected record."""
        self._json.append((role, value))
        local_id = self._local(role)
        uri = self.p.naming.reference(nsid, local_id)
        return _record(role, nsid, local_id, uri, value)

    def json_records(self) -> list[tuple[str, JsonObject]]:
        """Return the (role, value) pairs of the published records."""
        return self._json

    def published(self) -> list[ProjectedRecord]:
        """Build the published-shape records of the sentence."""
        p = self.p
        out = [self._emit("expr", EXPRESSION_NSID, self._expression())]
        out.append(
            self._emit(
                "seg",
                SEGMENTATION_NSID,
                {
                    "expression": self.expr_ref,
                    "createdAt": p.created_at,
                    "tokenizations": [self._surface(), self._word_tokenization()],
                },
            )
        )
        alignment = self._alignment()
        if alignment is not None:
            out.append(self._emit("align", ALIGNMENT_NSID, alignment))
        for role, layer in (
            ("upos", self._tag_layer(_SUBKIND_POS, UPOS)),
            ("xpos", self._tag_layer(_SUBKIND_XPOS, XPOS)),
            ("lemma", self._tag_layer(_SUBKIND_LEMMA, LEMMA)),
            ("morph", self._morph_layer()),
            ("deps", self._dependency_layer()),
        ):
            if layer is not None:
                out.append(self._emit(role, ANNOTATION_NSID, layer))
        enhanced = self._enhanced_layer()
        if enhanced is not None:
            out.append(
                self._emit(
                    "seg-enhanced",
                    SEGMENTATION_NSID,
                    {
                        "expression": self.expr_ref,
                        "createdAt": p.created_at,
                        "tokenizations": [self._enhanced_tokenization()],
                    },
                )
            )
            out.append(self._emit("edeps", ANNOTATION_NSID, enhanced))
        if p.corpus_ref is not None:
            membership = _drop_none(
                {
                    "corpusRef": p.corpus_ref,
                    "expressionRef": self.expr_ref,
                    "ordinal": self.ordinal,
                    "split": p.split,
                    "createdAt": p.created_at,
                }
            )
            out.append(self._emit("mem", MEMBERSHIP_NSID, membership))
        return out

    def _expression(self) -> JsonObject:
        """Return the sentence expression."""
        features = sorted(
            (key, value)
            for key, value in self.metadata.items()
            if key not in _STRUCTURAL_KEYS and value
        )
        return _drop_none(
            {
                "id": self.sid,
                "kind": "sentence",
                "text": self.text,
                "languages": list(self.p.languages) or None,
                "parentRef": self.parent,
                "features": _feature_map(features),
                "createdAt": self.p.created_at,
            }
        )

    def _tokens(
        self,
        forms: Iterable[tuple[str, tuple[int, int] | None]],
    ) -> list[JsonValue]:
        """Return tokens for (text, span) pairs, indexed in order."""
        tokens: list[JsonValue] = []
        for index, (form, span) in enumerate(forms):
            token: JsonObject = {"tokenIndex": index, "text": form}
            if span is not None:
                token["textSpan"] = {"byteStart": span[0], "byteEnd": span[1]}
            tokens.append(token)
        return tokens

    def _surface(self) -> JsonObject:
        """Return the surface tokenization."""
        forms = [
            (unit[0], span) for unit, span in zip(self.units, self.unit_spans, strict=True)
        ]
        return {
            "kind": "custom",
            "uuid": {"value": self.uuid_surface},
            "tokens": self._tokens(forms),
        }

    def _word_forms(self) -> list[tuple[str, tuple[int, int] | None]]:
        """Return the (form, span) of each word."""
        return [(row[FORM], self.word_spans.get(int(row[ID]))) for row in self.words]

    def _word_tokenization(self) -> JsonObject:
        """Return the syntactic-word tokenization."""
        return {
            "kind": "custom",
            "uuid": {"value": self.uuid_words},
            "tokens": self._tokens(self._word_forms()),
        }

    def _enhanced_tokenization(self) -> JsonObject:
        """Return the enhanced tokenization: the words, then the empty nodes."""
        forms = self._word_forms()
        forms.extend(
            ("" if row[FORM] == EMPTY else row[FORM], None) for row in self.empties
        )
        return {
            "kind": "custom",
            "uuid": {"value": self.uuid_enhanced},
            "tokens": self._tokens(forms),
        }

    def _alignment(self) -> JsonObject | None:
        """Return the multiword-token alignment, when the sentence has one."""
        if not any(len(unit[1]) > 1 for unit in self.units):
            return None
        index_of = {int(row[ID]): index for index, row in enumerate(self.words)}
        links: list[JsonValue] = []
        for surface_index, (_form, word_ids, misc, feats) in enumerate(self.units):
            entries = _published_misc(misc)
            entries.extend(
                (f"{_FEATS_LINK_PREFIX}{key}", value)
                for key, value in sorted(
                    (key, value)
                    for key, value in _pairs(feats).items()
                    if value is not None
                )
            )
            links.append(
                _drop_none(
                    {
                        "sourceIndices": [surface_index],
                        "targetIndices": [index_of[w] for w in word_ids if w in index_of],
                        "label": _MULTIWORD_LABEL if len(word_ids) > 1 else _ONE_TO_ONE_LABEL,
                        "features": _feature_map(entries),
                    }
                )
            )
        return {
            "createdAt": self.p.created_at,
            "expression": self.expr_ref,
            "kind": "tokenization-to-tokenization",
            "subkind": "word-to-word",
            "source": {"localId": {"value": self.uuid_surface}},
            "target": {"localId": {"value": self.uuid_words}},
            "links": links,
            "metadata": {"tool": self.p.tool},
        }

    def _layer(
        self,
        kind: str,
        subkind: str,
        label_set: str,
        annotations: list[JsonValue],
        *,
        ontology: str | None = None,
        uuid: str | None = None,
        parent: str | None = None,
    ) -> JsonObject:
        """Return an annotation layer over the sentence."""
        return _drop_none(
            {
                "annotations": annotations,
                "createdAt": self.p.created_at,
                "expression": self.expr_ref,
                "kind": kind,
                "subkind": subkind,
                "formalism": _FORMALISM,
                "sourceMethod": self.p.source_method,
                "labelSet": label_set,
                "ontologyRef": ontology,
                "parentLayerRef": parent,
                "tokenizationId": {"value": uuid or self.uuid_words},
            }
        )

    def _tag_layer(self, subkind: str, column: int) -> JsonObject | None:
        """Return a UPOS, XPOS, or lemma token-tag layer, or ``None`` when empty."""
        annotations: list[JsonValue] = []
        prefix = "upos" if subkind == _SUBKIND_POS else subkind
        for index, row in enumerate(self.words):
            value = row[column]
            if value == EMPTY:
                continue
            annotation: JsonObject = {
                "uuid": {"value": f"{prefix}-{index}"},
                "anchor": _anchor(index, self.uuid_words),
                "tokenIndex": index,
                "label": value,
            }
            if subkind == _SUBKIND_LEMMA:
                annotation["value"] = value
            elif subkind == _SUBKIND_POS:
                type_ref = self.p.ontology.pos_type(value)
                if type_ref is not None:
                    annotation["ontologyTypeRef"] = type_ref
            annotations.append(annotation)
        if subkind == _SUBKIND_POS:
            return self._layer(
                _TOKEN_TAG,
                subkind,
                "universal-pos",
                annotations,
                ontology=self.p.ontology.ontology("pos"),
            )
        if not annotations:
            return None
        label_set = "language-specific-pos" if subkind == _SUBKIND_XPOS else "lemma"
        return self._layer(_TOKEN_TAG, subkind, label_set, annotations)

    def _morph_layer(self) -> JsonObject | None:
        """Return the FEATS layer: one annotation per ``Feature=Value``."""
        annotations: list[JsonValue] = []
        for index, row in enumerate(self.words):
            for name, raw in _pairs(row[FEATS]).items():
                if raw is None:
                    continue
                feature = _feature_name(name)
                for part in raw.split(","):
                    value = part.strip()
                    if not value:
                        continue
                    resolved = self.p.ontology.feat(feature, value)
                    extra = [(entry.key, entry.value) for entry in resolved.extra]
                    annotations.append(
                        _drop_none(
                            {
                                "uuid": {"value": f"morph-{len(annotations)}"},
                                "anchor": _anchor(index, self.uuid_words),
                                "tokenIndex": index,
                                "label": f"{resolved.feature}={resolved.value}",
                                "value": resolved.literal,
                                "ontologyTypeRef": resolved.type_ref,
                                "features": _feature_map(extra),
                            }
                        )
                    )
        if not annotations:
            return None
        return self._layer(
            _TOKEN_TAG,
            _SUBKIND_MORPH,
            "universal-features",
            annotations,
            ontology=self.p.ontology.ontology("feats"),
        )

    def _dependency_layer(self) -> JsonObject:
        """Return the basic dependency layer (HEAD and DEPREL)."""
        annotations: list[JsonValue] = []
        for index, row in enumerate(self.words):
            if row[HEAD] == EMPTY or row[DEPREL] == EMPTY:
                continue
            head = int(row[HEAD])
            deprel = row[DEPREL]
            universal, subtype = _split_deprel(deprel)
            entries = [(_UD_RELATION, universal)]
            if subtype is not None:
                entries.append((_UD_SUBTYPE, subtype))
            entries.extend(_published_misc(row[MISC]))
            annotations.append(
                _drop_none(
                    {
                        "uuid": {"value": f"dep-{index}"},
                        "anchor": _anchor(index, self.uuid_words),
                        "tokenIndex": index,
                        "headIndex": _ROOT if head == 0 else head - 1,
                        "targetIndex": index,
                        "label": deprel,
                        "ontologyTypeRef": self.p.ontology.deprel_type(deprel),
                        "features": _feature_map(entries),
                    }
                )
            )
        return self._layer(
            _RELATION,
            _SUBKIND_DEPENDENCY,
            "universal-dependencies",
            annotations,
            ontology=self.p.ontology.ontology("deprel"),
        )

    def _enhanced_layer(self) -> JsonObject | None:
        """Return the enhanced dependency layer (DEPS), or ``None`` without arcs."""
        index_of: dict[str, int] = {row[ID]: i for i, row in enumerate(self.words)}
        for offset, row in enumerate(self.empties):
            index_of[row[ID]] = len(self.words) + offset
        annotations: list[JsonValue] = []
        for row in (*self.words, *self.empties):
            target = index_of.get(row[ID])
            if target is None:
                continue
            for item in split_items(row[DEPS]):
                head_text, _, relation = item.partition(":")
                head = _ROOT if head_text == "0" else index_of.get(head_text)
                if head is None:
                    continue
                universal, subtype = _split_deprel(relation)
                entries = [(_IS_ENHANCED, "true"), (_UD_RELATION, universal)]
                if subtype is not None:
                    entries.append((_UD_SUBTYPE, subtype))
                if "." in row[ID]:
                    entries.append((_UD_EMPTY_NODE, row[ID]))
                annotations.append(
                    _drop_none(
                        {
                            "uuid": {"value": f"edep-{len(annotations)}"},
                            "anchor": _anchor(target, self.uuid_enhanced),
                            "tokenIndex": target,
                            "headIndex": head,
                            "targetIndex": target,
                            "label": relation,
                            "ontologyTypeRef": self.p.ontology.deprel_type(relation),
                            "features": _feature_map(entries),
                        }
                    )
                )
        if not annotations:
            return None
        deps_ref = self.p.naming.reference(ANNOTATION_NSID, self._local("deps"))
        return self._layer(
            _RELATION,
            _SUBKIND_ENHANCED,
            "enhanced-universal-dependencies",
            annotations,
            ontology=self.p.ontology.ontology("deprel"),
            uuid=self.uuid_enhanced,
            parent=deps_ref,
        )

    def comment_carriers(self) -> list[JsonValue]:
        """Return the comment carrier entries, in comment order."""
        entries: list[JsonValue] = []
        sent_line = f"# sent_id = {self.sid}"
        text_line = f"# text = {self.text}"
        for line in self.comment_lines:
            if line == sent_line:
                entries.append({"key": _K_COMMENT_REF, "value": "sent_id"})
            elif line == text_line:
                entries.append({"key": _K_COMMENT_REF, "value": "text"})
            else:
                entries.extend(_carrier_entries(_K_COMMENT, line[1:]))
        return entries

    def carrier_layer(self, rows: list[tuple[str, list[JsonValue]]]) -> ProjectedRecord:
        """Return the carrier layer for the rows the published shape misses."""
        word_index = {row[ID]: index for index, row in enumerate(self.words)}
        annotations: list[JsonValue] = []
        for row_id, entries in rows:
            annotation: JsonObject = {
                "uuid": {"value": f"conllu-{len(annotations)}"},
                "label": row_id,
            }
            index = word_index.get(row_id)
            if index is not None:
                annotation["anchor"] = _anchor(index, self.uuid_words)
                annotation["tokenIndex"] = index
            annotation["features"] = {"entries": entries}
            annotations.append(annotation)
        layer = self._layer(_TOKEN_TAG, CARRIER_SUBKIND, "conllu-columns", annotations)
        return self._emit("conllu", ANNOTATION_NSID, layer)


def _row_carriers(
    predicted: dict[str, tuple[str, ...]],
    rows: Sequence[tuple[str, ...]],
) -> list[tuple[str, list[JsonValue]]]:
    """Return the carrier entries of every row the prediction gets wrong."""
    carriers: list[tuple[str, list[JsonValue]]] = []
    seen: set[str] = set()
    for row in rows:
        row_id = row[ID]
        if row_id in seen:
            message = f"duplicate row id {row_id!r}"
            raise ValueError(message)
        seen.add(row_id)
        guess = predicted.get(row_id)
        entries: list[JsonValue] = []
        for column in range(FORM, COLUMNS):
            if guess is None or guess[column] != row[column]:
                entries.extend(_carrier_entries(_COLUMN_KEYS[column], row[column]))
        if entries:
            carriers.append((row_id, entries))
    carriers.extend(
        (row_id, [{"key": _K_DROP, "value": "true"}])
        for row_id in predicted
        if row_id not in seen
    )
    return carriers


# -----------------------------------------------------------------------------
# inverse
# -----------------------------------------------------------------------------


def _obj(value: JsonValue | None) -> JsonObject | None:
    """Return ``value`` when it is a JSON object."""
    return value if isinstance(value, dict) else None


def _list(value: JsonValue | None) -> list[JsonValue]:
    """Return ``value`` when it is a JSON array, else an empty list."""
    return value if isinstance(value, list) else []


def _str(value: JsonValue | None) -> str | None:
    """Return ``value`` when it is a string."""
    return value if isinstance(value, str) else None


def _int(value: JsonValue | None) -> int | None:
    """Return ``value`` when it is an integer (not a boolean)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _uuid_of(value: JsonValue | None) -> str | None:
    """Return the ``value`` of a uuid object."""
    obj = _obj(value)
    return _str(obj.get("value")) if obj is not None else None


def _entries(value: JsonValue | None) -> list[tuple[str, str]]:
    """Return the (key, value) entries of a feature map."""
    obj = _obj(value)
    if obj is None:
        return []
    pairs: list[tuple[str, str]] = []
    for entry in _list(obj.get("entries")):
        item = _obj(entry)
        if item is None:
            continue
        key = _str(item.get("key"))
        val = _str(item.get("value"))
        if key is not None and val is not None:
            pairs.append((key, val))
    return pairs


def _carrier_values(entries: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Return the carrier entries of a feature list, continuations joined."""
    out: list[tuple[str, str]] = []
    for key, value in entries:
        if key == _K_MORE and out:
            last_key, last_value = out[-1]
            out[-1] = (last_key, last_value + value)
        elif key.startswith(CARRIER_PREFIX):
            out.append((key, value))
    return out


def _annotations(layer: JsonObject | None) -> list[JsonObject]:
    """Return the annotation objects of a layer."""
    if layer is None:
        return []
    return [a for a in _list(layer.get("annotations")) if isinstance(a, dict)]


def _index(annotation: JsonObject) -> int | None:
    """Return the token index an annotation targets."""
    index = _int(annotation.get("tokenIndex"))
    if index is not None:
        return index
    anchor = _obj(annotation.get("anchor"))
    ref = _obj(anchor.get("tokenRef")) if anchor is not None else None
    return _int(ref.get("tokenIndex")) if ref is not None else None


class _Prediction:
    """A sentence reconstructed from the published shape alone."""

    def __init__(self) -> None:
        self.columns: dict[str, tuple[str, ...]] = {}
        self.lossy: set[str] = set()


def _tokens_of(tokenization: JsonObject | None) -> list[JsonObject]:
    """Return the tokens of a tokenization, ordered by index."""
    if tokenization is None:
        return []
    tokens = [t for t in _list(tokenization.get("tokens")) if isinstance(t, dict)]
    return sorted(tokens, key=lambda t: _int(t.get("tokenIndex")) or 0)


def _span(token: JsonObject) -> tuple[int, int] | None:
    """Return a token's byte span."""
    span = _obj(token.get("textSpan"))
    if span is None:
        return None
    start = _int(span.get("byteStart"))
    end = _int(span.get("byteEnd"))
    return None if start is None or end is None else (start, end)


class _Records:
    """One sentence's records, sorted by role."""

    def __init__(
        self,
        segmentations: Sequence[JsonObject],
        layers: Sequence[JsonObject],
        alignments: Sequence[JsonObject],
    ) -> None:
        self.tokenizations: dict[str, JsonObject] = {}
        self.order: list[list[str]] = []
        for segmentation in segmentations:
            uuids: list[str] = []
            for tokenization in _list(segmentation.get("tokenizations")):
                obj = _obj(tokenization)
                uuid = _uuid_of(obj.get("uuid")) if obj is not None else None
                if obj is not None and uuid is not None:
                    self.tokenizations[uuid] = obj
                    uuids.append(uuid)
            self.order.append(uuids)
        self.layers: dict[str, JsonObject] = {}
        for layer in layers:
            subkind = _str(layer.get("subkind"))
            if subkind is not None and subkind not in self.layers:
                self.layers[subkind] = layer
        self.alignment: JsonObject | None = None
        for alignment in alignments:
            if _str(alignment.get("subkind")) == "word-to-word":
                self.alignment = alignment
                break
        self.words_uuid = self._words_uuid()
        self.surface_uuid = self._surface_uuid()
        enhanced = self.layers.get(_SUBKIND_ENHANCED)
        self.enhanced_uuid = (
            _uuid_of(enhanced.get("tokenizationId")) if enhanced is not None else None
        )

    def _words_uuid(self) -> str | None:
        """Identify the syntactic-word tokenization."""
        for subkind in (
            _SUBKIND_DEPENDENCY,
            _SUBKIND_POS,
            _SUBKIND_LEMMA,
            _SUBKIND_XPOS,
            _SUBKIND_MORPH,
            CARRIER_SUBKIND,
        ):
            layer = self.layers.get(subkind)
            uuid = _uuid_of(layer.get("tokenizationId")) if layer is not None else None
            if uuid is not None and uuid in self.tokenizations:
                return uuid
        if self.alignment is not None:
            target = _obj(self.alignment.get("target"))
            uuid = _uuid_of(target.get("localId")) if target is not None else None
            if uuid is not None:
                return uuid
        for uuids in self.order:
            if uuids:
                return uuids[-1]
        return None

    def _surface_uuid(self) -> str | None:
        """Identify the surface tokenization."""
        if self.alignment is not None:
            source = _obj(self.alignment.get("source"))
            uuid = _uuid_of(source.get("localId")) if source is not None else None
            if uuid is not None:
                return uuid
        for uuids in self.order:
            if self.words_uuid in uuids:
                others = [u for u in uuids if u != self.words_uuid]
                return others[0] if others else self.words_uuid
        return self.words_uuid


def _morph_columns(layer: JsonObject | None) -> dict[int, str]:
    """Regroup morph annotations into a FEATS column per word."""
    items: dict[int, list[tuple[str, str]]] = {}
    for annotation in _annotations(layer):
        index = _index(annotation)
        label = _str(annotation.get("label"))
        if index is None or label is None:
            continue
        original = dict(_entries(annotation.get("features"))).get(_UD_FEATS_ORIGINAL)
        feature, _, value = (original or label).partition("=")
        group = items.setdefault(index, [])
        if group and group[-1][0] == feature:
            group[-1] = (feature, f"{group[-1][1]},{value}")
        else:
            group.append((feature, value))
    return {
        index: "|".join(f"{name}={value}" for name, value in pairs)
        for index, pairs in items.items()
    }


def _labels(layer: JsonObject | None, *, prefer_value: bool = False) -> dict[int, str]:
    """Return the label (or value) of each annotated word."""
    labels: dict[int, str] = {}
    for annotation in _annotations(layer):
        index = _index(annotation)
        label = _str(annotation.get("value")) if prefer_value else None
        label = label or _str(annotation.get("label"))
        if index is not None and label is not None:
            labels[index] = label
    return labels


def _predict(json_records: Sequence[tuple[str, JsonObject]]) -> _Prediction:
    """Predict a sentence's rows from its published-shape records (forward side)."""
    segmentations = [v for role, v in json_records if role in {"seg", "seg-enhanced"}]
    alignments = [v for role, v in json_records if role == "align"]
    layers = [
        v for role, v in json_records if role in {"upos", "xpos", "lemma", "morph", "deps", "edeps"}
    ]
    return _rows_from(_Records(segmentations, layers, alignments))


def _rows_from(records: _Records) -> _Prediction:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Reconstruct every row's columns from the published shape."""
    prediction = _Prediction()
    words = _tokens_of(records.tokenizations.get(records.words_uuid or ""))
    count = len(words)
    layers = records.layers
    lemmas = _labels(layers.get(_SUBKIND_LEMMA), prefer_value=True)
    upos = _labels(layers.get(_SUBKIND_POS))
    xpos = _labels(layers.get(_SUBKIND_XPOS))
    feats = _morph_columns(layers.get(_SUBKIND_MORPH))
    if layers.get(_SUBKIND_MORPH) is not None:
        prediction.lossy.add(LOSSY_FEATS)
    heads: dict[int, tuple[str, str]] = {}
    misc: dict[int, list[tuple[str, str]]] = {}
    for annotation in _annotations(layers.get(_SUBKIND_DEPENDENCY)):
        index = _index(annotation)
        head = _int(annotation.get("headIndex"))
        label = _str(annotation.get("label"))
        if index is None or head is None or label is None:
            continue
        heads[index] = ("0" if head == _ROOT else str(head + 1), label)
        misc[index] = [
            (key, value)
            for key, value in _entries(annotation.get("features"))
            if key not in {_UD_RELATION, _UD_SUBTYPE} and not key.startswith(CARRIER_PREFIX)
        ]

    # enhanced arcs: the enhanced index of each empty node, and each node's arcs.
    enhanced_tokens = _tokens_of(records.tokenizations.get(records.enhanced_uuid or ""))
    empty_ids: dict[int, str] = {}
    arcs: list[tuple[int, int, str]] = []
    for annotation in _annotations(layers.get(_SUBKIND_ENHANCED)):
        target = _int(annotation.get("targetIndex"))
        target = _index(annotation) if target is None else target
        head = _int(annotation.get("headIndex"))
        label = _str(annotation.get("label"))
        if target is None or head is None or label is None:
            continue
        empty = dict(_entries(annotation.get("features"))).get(_UD_EMPTY_NODE)
        if empty is not None:
            empty_ids[target] = empty
        arcs.append((target, head, label))
    deps: dict[str, list[str]] = {}
    for target, head, label in arcs:
        target_id = str(target + 1) if target < count else empty_ids.get(target)
        if head == _ROOT:
            head_id: str | None = "0"
        elif head < count:
            head_id = str(head + 1)
        else:
            head_id = empty_ids.get(head)
        if target_id is None or head_id is None:
            prediction.lossy.add(LOSSY_DEPS)
            continue
        deps.setdefault(target_id, []).append(f"{head_id}:{label}")

    # surface units: ranges and SpaceAfter.
    surface = _tokens_of(records.tokenizations.get(records.surface_uuid or ""))
    units = _surface_units(records, surface, words)
    space_no: set[str] = set()
    for position, (row_id, span, _form, _entries_) in enumerate(units):
        if span is None or position + 1 >= len(units):
            continue
        following = units[position + 1][1]
        if following is not None and following[0] == span[1]:
            space_no.add(row_id)
    columns = prediction.columns
    for row_id, _span_, form, link_entries in units:
        if "-" not in row_id:
            continue
        prediction.lossy.add(LOSSY_MULTIWORD)
        pairs = [(k, v) for k, v in link_entries if not k.startswith(_FEATS_LINK_PREFIX)]
        if row_id in space_no:
            pairs.append((_SPACE_AFTER, "No"))
        range_feats = "|".join(
            f"{k.removeprefix(_FEATS_LINK_PREFIX)}={v}"
            for k, v in link_entries
            if k.startswith(_FEATS_LINK_PREFIX)
        )
        columns[row_id] = (
            row_id, form, EMPTY, EMPTY, EMPTY, range_feats or EMPTY,
            EMPTY, EMPTY, EMPTY, _render_pairs(sorted(pairs, key=lambda p: p[0])),
        )  # fmt: skip
    for index, token in enumerate(words):
        row_id = str(index + 1)
        form = _str(token.get("text")) or EMPTY
        head, deprel = heads.get(index, (EMPTY, EMPTY))
        pairs = list(misc.get(index, []))
        if row_id in space_no:
            pairs.append((_SPACE_AFTER, "No"))
        lemma = lemmas.get(index, EMPTY)
        columns[row_id] = (
            row_id, form, lemma, upos.get(index, EMPTY), xpos.get(index, EMPTY),
            feats.get(index, EMPTY), head, deprel, "|".join(deps.get(row_id, [])) or EMPTY,
            _render_pairs(sorted(pairs, key=lambda p: p[0])),
        )  # fmt: skip
    for index in range(count, len(enhanced_tokens)):
        row_id = empty_ids.get(index)
        if row_id is None:
            prediction.lossy.add(LOSSY_EMPTY_NODES)
            continue
        prediction.lossy.add(LOSSY_EMPTY_NODES)
        form = _str(enhanced_tokens[index].get("text")) or EMPTY
        columns[row_id] = (
            row_id, form, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY,
            "|".join(deps.get(row_id, [])) or EMPTY, EMPTY,
        )  # fmt: skip
    prediction.lossy.add(LOSSY_MISC)
    return prediction


def _surface_units(
    records: _Records,
    surface: Sequence[JsonObject],
    words: Sequence[JsonObject],
) -> list[tuple[str, tuple[int, int] | None, str, list[tuple[str, str]]]]:
    """Return the surface units as (row id, span, form, link entries).

    The row id is a word id for a single word and a range id for a multiword
    token. The units come from the alignment when present, and otherwise from
    runs of consecutive words sharing one byte span.
    """
    units: list[tuple[str, tuple[int, int] | None, str, list[tuple[str, str]]]] = []
    if records.alignment is not None:
        for link_value in _list(records.alignment.get("links")):
            link = _obj(link_value)
            if link is None:
                continue
            sources = [i for i in _list(link.get("sourceIndices")) if isinstance(i, int)]
            targets = [i for i in _list(link.get("targetIndices")) if isinstance(i, int)]
            if not sources or not targets:
                continue
            token = surface[sources[0]] if sources[0] < len(surface) else None
            span = _span(token) if token is not None else None
            form = (_str(token.get("text")) if token is not None else None) or EMPTY
            entries = _entries(link.get("features"))
            if len(targets) > 1:
                row_id = f"{min(targets) + 1}-{max(targets) + 1}"
            else:
                row_id = str(targets[0] + 1)
            units.append((row_id, span, form, entries))
        return units
    surface_by_span = {_span(token): token for token in surface}
    index = 0
    while index < len(words):
        span = _span(words[index])
        end = index
        while (
            span is not None
            and end + 1 < len(words)
            and _span(words[end + 1]) == span
        ):
            end += 1
        if end > index:
            token = surface_by_span.get(span)
            form = (_str(token.get("text")) if token is not None else None) or EMPTY
            units.append((f"{index + 1}-{end + 1}", span, form, []))
        else:
            units.append((str(index + 1), span, "", []))
        index = end + 1
    return units


def _comments_lossy(
    expression: JsonObject,
    opened: Sequence[JsonObject],
) -> list[str]:
    """Reconstruct comment lines from the published expression fields."""
    lines: list[str] = []
    for unit in opened:
        kind = _str(unit.get("kind"))
        unit_id = _str(unit.get("id")) or ""
        marker = "newdoc" if kind == "document" else "newpar"
        if unit_id.startswith(f"{marker}:"):
            lines.append(f"# {marker}")
        else:
            lines.append(f"# {marker} id = {unit_id}")
    sent_id = _str(expression.get("id"))
    if sent_id is not None:
        lines.append(f"# sent_id = {sent_id}")
    lines.extend(
        f"# {key} = {value}"
        for key, value in _entries(expression.get("features"))
        if not key.startswith(CARRIER_PREFIX)
    )
    text = _str(expression.get("text"))
    if text is not None:
        lines.append(f"# text = {text}")
    return lines


def sentence_from_json(
    expression: JsonObject,
    segmentations: Sequence[JsonObject] = (),
    layers: Sequence[JsonObject] = (),
    alignments: Sequence[JsonObject] = (),
    *,
    opened: Sequence[JsonObject] = (),
) -> ConlluSentence:
    """Rebuild one CoNLL-U sentence from its records' JSON values.

    Parameters
    ----------
    expression : JsonObject
        The sentence expression.
    segmentations : collections.abc.Sequence of JsonObject, optional
        The segmentations referencing it.
    layers : collections.abc.Sequence of JsonObject, optional
        The annotation layers referencing it.
    alignments : collections.abc.Sequence of JsonObject, optional
        The alignments referencing it.
    opened : collections.abc.Sequence of JsonObject, optional
        The document and paragraph expressions this sentence opens, outermost
        first. Used only to restore ``# newdoc`` and ``# newpar`` comments when
        the comment carriers are absent.

    Returns
    -------
    ConlluSentence
        The sentence; :attr:`~lairs.conllu.model.ConlluSentence.lossy` names
        any field that was reconstructed rather than restored exactly.

    Raises
    ------
    ValueError
        When the records hold no token rows to rebuild.
    """
    records = _Records(segmentations, layers, alignments)
    prediction = _rows_from(records)
    columns = prediction.columns
    carriers = _carrier_values(_entries(expression.get("features")))
    scheme = any(key == _K_SCHEME for key, _ in carriers)
    lossy: set[str] = set()
    order: list[str] | None = None
    if scheme:
        expected = 0
        for key, value in carriers:
            if key == _K_ROWS:
                expected = int(value)
            elif key == _K_ORDER:
                order = value.split(" ")
        found = _apply_row_carriers(records.layers.get(CARRIER_SUBKIND), columns)
        if found != expected:
            lossy = prediction.lossy | {LOSSY_CARRIERS}
        comment_lines = _comments_carried(expression, carriers)
    else:
        lossy = prediction.lossy | {LOSSY_COMMENTS}
        comment_lines = _comments_lossy(expression, opened)
    ids = order if order is not None else sorted(columns, key=_row_key)
    rows = ["\t".join(columns[row_id]) for row_id in ids if row_id in columns]
    if not rows:
        message = "the records hold no token rows"
        raise ValueError(message)
    return ConlluSentence.build(comment_lines, rows, lossy=sorted(lossy))


def _apply_row_carriers(
    layer: JsonObject | None,
    columns: dict[str, tuple[str, ...]],
) -> int:
    """Apply the carrier layer's row overrides and return how many it holds."""
    found = 0
    for annotation in _annotations(layer):
        row_id = _str(annotation.get("label"))
        if row_id is None:
            continue
        found += 1
        values = _carrier_values(_entries(annotation.get("features")))
        if any(key == _K_DROP for key, _ in values):
            columns.pop(row_id, None)
            continue
        row = list(columns.get(row_id, (row_id, *([EMPTY] * (COLUMNS - 1)))))
        for key, value in values:
            column = _KEY_COLUMNS.get(key)
            if column is not None:
                row[column] = value
        columns[row_id] = tuple(row)
    return found


def _comments_carried(
    expression: JsonObject,
    carriers: Sequence[tuple[str, str]],
) -> list[str]:
    """Restore comment lines from the comment carriers."""
    lines: list[str] = []
    for key, value in carriers:
        if key == _K_COMMENT:
            lines.append(f"#{value}")
        elif key == _K_COMMENT_REF:
            field = "id" if value == "sent_id" else value
            lines.append(f"# {value} = {_str(expression.get(field)) or ''}")
    return lines


def _model_json(model: LayersRecord) -> JsonObject:
    """Return a record model's value as JSON."""
    value = json.loads(model.model_dump_json())
    if not isinstance(value, dict):
        message = "record model did not dump to a JSON object"
        raise TypeError(message)
    return value


def sentence_from_records(
    expression: Expression,
    segmentations: Iterable[Segmentation] = (),
    layers: Iterable[AnnotationLayer] = (),
    alignments: Iterable[Alignment] = (),
    *,
    opened: Iterable[Expression] = (),
) -> ConlluSentence:
    """Rebuild one CoNLL-U sentence from its record models.

    A convenience over :func:`sentence_from_json` that dumps each model to
    JSON first; prefer the JSON form on hot paths.

    Parameters
    ----------
    expression : Expression
        The sentence expression.
    segmentations : collections.abc.Iterable of Segmentation, optional
        The segmentations referencing it.
    layers : collections.abc.Iterable of AnnotationLayer, optional
        The annotation layers referencing it.
    alignments : collections.abc.Iterable of Alignment, optional
        The alignments referencing it.
    opened : collections.abc.Iterable of Expression, optional
        The document and paragraph expressions the sentence opens.

    Returns
    -------
    ConlluSentence
        The sentence.
    """
    return sentence_from_json(
        _model_json(expression),
        [_model_json(s) for s in segmentations],
        [_model_json(layer) for layer in layers],
        [_model_json(a) for a in alignments],
        opened=[_model_json(unit) for unit in opened],
    )
