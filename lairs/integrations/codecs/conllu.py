"""CoNLL-U format codec.

Converts between CoNLL-U (Universal Dependencies) and lairs records, binding to
the :class:`~lairs.integrations.ports.Codec` port. The optional ``conllu``
library (the ``lairs[conllu]`` extra) is imported lazily inside the codec
methods, with a clear error when it is missing, so importing this module never
pulls the dependency in.

:class:`ConlluCodec` parses with the ``conllu`` library (``conllu.parse``) and
serialises with its ``TokenList.serialize``, so it inherits that library's
multi-sentence, comment, multiword-token, and sentence-metadata handling. The
:class:`ConlluIso` works over already-parsed structures with a self-contained
standard-library parser, so it never requires the optional dependency.

The CoNLL-U surface maps onto Layers as follows:

- the ``FORM`` column of each token-line becomes a
  :class:`~lairs.records.segmentation.Token`, and a sentence's tokens become a
  :class:`~lairs.records.segmentation.Tokenization` inside one
  :class:`~lairs.records.segmentation.Segmentation` record. Each token's
  ``textSpan`` carries the true UTF-8 byte offsets of its form in the sentence
  text (the tokens are joined with single spaces).
- ``UPOS`` and ``XPOS`` become token-tag
  :class:`~lairs.records.annotation.AnnotationLayer` records anchored by token
  index; ``LEMMA`` becomes a token-tag lemma layer; ``FEATS`` are carried as
  per-annotation features.
- ``HEAD``/``DEPREL`` become a relation (dependency) annotation layer, with each
  arc carrying ``headIndex`` (``-1`` at the root) and ``targetIndex``.

Only the basic ``HEAD``/``DEPREL`` dependency tree is modelled. The CoNLL-U
``DEPS`` column (enhanced Universal Dependencies, which may attach several
governors to one token) is not decoded: the relation layer models exactly one
head per token. Multiword-token range rows (``1-2``) and empty-node rows
(``1.1``) are skipped; their surface text is recovered from the per-token forms.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.integrations.codecs import CorpusFragment, FragmentRecord
from lairs.records._generated.annotation import Annotation, AnnotationLayer
from lairs.records._generated.defs import (
    Anchor,
    Feature,
    FeatureMap,
    Span,
    TokenRef,
    Uuid,
)
from lairs.records._generated.expression import Expression
from lairs.records._generated.segmentation import Segmentation, Token, Tokenization

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from types import ModuleType

    from lairs._types import JsonValue

__all__ = ["ConlluCodec", "ConlluIso"]

# the epoch timestamp used for the deterministic createdAt of generated records.
_EPOCH = "1970-01-01T00:00:00+00:00"

# the at-uri-shaped local reference the generated records point at, before the
# per-sentence index suffix is appended.
_EXPRESSION_REF = "at://local/expression"

# the deterministic uuid stem of the generated tokenization.
_TOKENIZATION_UUID = "tokenization"

# the nsid collections of the records a conllu fragment carries.
_EXPRESSION_NSID = "pub.layers.expression"
_SEGMENTATION_NSID = "pub.layers.segmentation"
_ANNOTATION_NSID = "pub.layers.annotation"

# the local-id stems of the records inside a conllu fragment, before the
# per-sentence index suffix is appended.
_EXPRESSION_LOCAL_ID = "expression"
_SEGMENTATION_LOCAL_ID = "segmentation"
_UPOS_LAYER_LOCAL_ID = "upos"
_XPOS_LAYER_LOCAL_ID = "xpos"
_LEMMA_LAYER_LOCAL_ID = "lemma"
_DEPS_LAYER_LOCAL_ID = "dependencies"

# the conllu sentinel for an absent column value.
_EMPTY = "_"

# the head index of the dependency root.
_ROOT_HEAD = -1


def _require_conllu() -> ModuleType:
    """Import and return the optional ``conllu`` library, or raise a clear error.

    Returns
    -------
    types.ModuleType
        The imported ``conllu`` module.

    Raises
    ------
    ModuleNotFoundError
        When the ``conllu`` library is not installed.
    """
    try:
        import conllu  # noqa: PLC0415
    except ImportError as error:
        message = (
            "the conllu codec requires the optional 'conllu' library; "
            "install it with `pip install lairs[conllu]`"
        )
        raise ModuleNotFoundError(message) from error
    return conllu


class ConlluCodec:
    """A bidirectional CoNLL-U codec.

    Decodes CoNLL-U text into a
    :class:`~lairs.integrations.codecs.CorpusFragment` carrying an expression
    record, a segmentation record, token-tag layers for ``UPOS``/``XPOS``/lemma,
    and a relation layer for the dependency parse. Encoding reverses the
    transform.
    """

    name = "conllu"

    def decode(
        self,
        src: str | bytes,
        *,
        into: CorpusFragment | None = None,
    ) -> CorpusFragment:
        """Decode CoNLL-U text into a corpus fragment.

        Every sentence in the source is decoded. Each sentence contributes its
        own expression, segmentation, and annotation-layer records, with the
        local ids and uuids suffixed by the sentence's 0-based index (the first
        sentence keeps the unsuffixed ids for symmetry with the single-sentence
        :class:`ConlluIso`).

        Parameters
        ----------
        src : str or bytes
            The CoNLL-U source, which may hold any number of sentences.
        into : lairs.integrations.codecs.CorpusFragment or None, optional
            An existing fragment to extend with the decoded records.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The decoded fragment.

        Raises
        ------
        ModuleNotFoundError
            When the optional ``conllu`` library is not installed.
        """
        conllu = _require_conllu()
        sentences = _parse_with_library(conllu, _as_str(src))
        records = list(into.records) if into is not None else []
        for index, sentence in enumerate(sentences):
            records.extend(_records_from_sentence(sentence, index))
        return CorpusFragment(records=tuple(records), source=self.name)

    def encode(self, records: Iterable[FragmentRecord]) -> str:
        """Encode fragment records into CoNLL-U text.

        Records are grouped back into their sentences (by the index suffix the
        decode side assigned), and each sentence is serialised with the
        ``conllu`` library's ``TokenList.serialize`` so the output is conformant
        CoNLL-U.

        Parameters
        ----------
        records : collections.abc.Iterable of FragmentRecord
            The records to encode.

        Returns
        -------
        str
            The CoNLL-U representation.

        Raises
        ------
        ModuleNotFoundError
            When the optional ``conllu`` library is not installed.
        """
        conllu = _require_conllu()
        sentences = _sentences_from_records(tuple(records))
        return "".join(_render_with_library(conllu, sentence) for sentence in sentences)


class _Feat(dx.Model):
    """A single CoNLL-U morphological feature key/value pair.

    Attributes
    ----------
    key : str
        The feature name (for example ``"Number"``).
    value : str
        The feature value (for example ``"Sing"``).
    """

    key: str = dx.field(description="feature name")
    value: str = dx.field(description="feature value")


class _ConlluToken(dx.Model):
    """A single parsed CoNLL-U token row.

    Attributes
    ----------
    index : int
        The 0-based token index (one less than the CoNLL-U ``ID``).
    form : str
        The ``FORM`` surface form.
    lemma : str or None
        The ``LEMMA`` value, if present.
    upos : str or None
        The ``UPOS`` universal part-of-speech tag, if present.
    xpos : str or None
        The ``XPOS`` language-specific part-of-speech tag, if present.
    feats : tuple of _Feat, optional
        The ordered ``FEATS`` key/value pairs.
    head : int or None
        The ``HEAD`` 0-based governor index (``-1`` for the root), if present.
    deprel : str or None
        The ``DEPREL`` dependency relation label, if present.
    """

    index: int = dx.field(description="0-based token index")
    form: str = dx.field(description="surface form")
    lemma: str | None = dx.field(default=None, description="lemma")
    upos: str | None = dx.field(default=None, description="universal pos tag")
    xpos: str | None = dx.field(default=None, description="language-specific pos tag")
    feats: tuple[_Feat, ...] = dx.field(
        default=(),
        description="ordered morphological feature pairs",
    )
    head: int | None = dx.field(default=None, description="0-based head index")
    deprel: str | None = dx.field(default=None, description="dependency relation")


class _ConlluSentence(dx.Model):
    """A single parsed CoNLL-U sentence.

    Attributes
    ----------
    text : str
        The reconstructed sentence text.
    tokens : tuple of _ConlluToken
        The token rows, in order.
    """

    text: str = dx.field(description="reconstructed sentence text")
    tokens: tuple[_ConlluToken, ...] = dx.field(default=(), description="token rows")


class ConlluIso(dx.Iso[_ConlluSentence, CorpusFragment]):
    """An :class:`~didactic.api.Iso` between a CoNLL-U sentence and a fragment.

    The forward direction builds a corpus fragment from a parsed sentence; the
    backward direction recovers the sentence. Round-trip law fixtures verify
    that ``backward(forward(x)) == x`` on the supported subset (one tokenisation
    with ``UPOS``/``XPOS``/lemma tags, morphological features, and a projective
    dependency tree). This Iso operates over parsed structures, so it does not
    require the optional ``conllu`` library.
    """

    def forward(self, a: _ConlluSentence, /) -> CorpusFragment:
        """Build a corpus fragment from a parsed sentence.

        Parameters
        ----------
        a : _ConlluSentence
            The parsed CoNLL-U sentence.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The fragment of expression, segmentation, and layer records.
        """
        return CorpusFragment(
            records=tuple(_records_from_sentence(a)),
            source="conllu",
        )

    def backward(self, b: CorpusFragment, /) -> _ConlluSentence:
        """Recover a parsed sentence from a corpus fragment.

        Parameters
        ----------
        b : lairs.integrations.codecs.CorpusFragment
            The fragment to recover the sentence from.

        Returns
        -------
        _ConlluSentence
            The parsed CoNLL-U sentence.
        """
        return _sentence_from_records(b.records)


def _as_str(src: str | bytes) -> str:
    """Return ``src`` decoded to text, treating bytes as UTF-8."""
    if isinstance(src, bytes):
        return src.decode("utf-8")
    return src


def _suffix(stem: str, index: int) -> str:
    """Return ``stem`` for sentence 0, else ``stem`` with a ``-index`` suffix.

    Sentence 0 keeps the unsuffixed stem so a single-sentence decode matches the
    :class:`ConlluIso` output exactly.
    """
    return stem if index == 0 else f"{stem}-{index}"


def _local_id(stem: str, index: int) -> str:
    """Return the per-sentence local id of a record built from ``stem``."""
    return _suffix(stem, index)


def _expression_ref(index: int) -> str:
    """Return the per-sentence expression reference for sentence ``index``."""
    return _suffix(_EXPRESSION_REF, index)


def _tokenization_uuid(index: int) -> str:
    """Return the per-sentence tokenization uuid for sentence ``index``."""
    return f"{_TOKENIZATION_UUID}-{index}"


def _annotation_uuid(prefix: str, index: int, token_index: int) -> str:
    """Return a per-sentence, per-token annotation uuid."""
    if index == 0:
        return f"{prefix}-{token_index}"
    return f"{prefix}-{index}-{token_index}"


def _sentence_index_of(local_id: str, stem: str) -> int | None:
    """Return the sentence index a record's ``local_id`` encodes, or ``None``.

    A bare stem (``"expression"``) maps to sentence 0; a suffixed stem
    (``"expression-3"``) maps to that index. A ``local_id`` that does not match
    the stem returns ``None``.
    """
    if local_id == stem:
        return 0
    prefix = f"{stem}-"
    if not local_id.startswith(prefix):
        return None
    suffix = local_id[len(prefix) :]
    try:
        return int(suffix)
    except ValueError:
        return None


def _parse_conllu(src: str) -> _ConlluSentence:
    """Parse the first CoNLL-U sentence in ``src`` into a :class:`_ConlluSentence`.

    The parse itself only depends on the standard library so the Iso path stays
    dependency-free; the caller requires the optional ``conllu`` library when
    decoding through :class:`ConlluCodec`.
    """
    tokens: list[_ConlluToken] = []
    declared_text: str | None = None
    for raw in src.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            if tokens:
                break
            continue
        if line.startswith("#"):
            key, _, value = line[1:].partition("=")
            if key.strip() == "text":
                declared_text = value.strip()
            continue
        token = _parse_token_line(line)
        if token is not None:
            tokens.append(token)
    text = declared_text if declared_text is not None else _join_forms(tokens)
    return _ConlluSentence(text=text, tokens=tuple(tokens))


def _parse_with_library(conllu: ModuleType, src: str) -> tuple[_ConlluSentence, ...]:
    """Parse every CoNLL-U sentence in ``src`` with the ``conllu`` library."""
    return tuple(
        _sentence_from_token_list(token_list) for token_list in conllu.parse(src)
    )


def _sentence_from_token_list(
    token_list: Iterable[dict[str, object]],
) -> _ConlluSentence:
    """Convert one ``conllu`` ``TokenList`` into a :class:`_ConlluSentence`."""
    metadata = getattr(token_list, "metadata", {}) or {}
    declared_text = metadata.get("text") if isinstance(metadata, dict) else None
    tokens: list[_ConlluToken] = []
    for row in token_list:
        token = _token_from_library_row(row)
        if token is not None:
            tokens.append(token)
    text = declared_text if isinstance(declared_text, str) else _join_forms(tokens)
    return _ConlluSentence(text=text, tokens=tuple(tokens))


def _token_from_library_row(row: dict[str, object]) -> _ConlluToken | None:
    """Convert one ``conllu`` token mapping into a :class:`_ConlluToken`.

    Multiword-token range rows (``id`` is a tuple) and empty-node rows are
    skipped so the segmentation models exactly the syntactic words.
    """
    token_id = row.get("id")
    if not isinstance(token_id, int):
        # multiword ranges parse to a tuple id; empty nodes to a decimal tuple.
        return None
    return _ConlluToken(
        index=token_id - 1,
        form=str(row.get("form", "")),
        lemma=_library_str(row.get("lemma")),
        upos=_library_str(row.get("upos")),
        xpos=_library_str(row.get("xpos")),
        feats=_library_feats(row.get("feats")),
        head=_library_head(row.get("head")),
        deprel=_library_str(row.get("deprel")),
    )


def _library_str(value: object) -> str | None:
    """Return a library column value as a string, or ``None`` when absent."""
    if value is None or value == _EMPTY:
        return None
    return str(value)


def _library_feats(value: object) -> tuple[_Feat, ...]:
    """Convert a library ``feats`` mapping into ordered key/value pairs."""
    if not isinstance(value, dict):
        return ()
    return tuple(
        _Feat(key=str(key), value=str(val))
        for key, val in value.items()
        if val is not None
    )


def _library_head(value: object) -> int | None:
    """Convert a library ``head`` value into a 0-based head index (``-1`` root)."""
    if not isinstance(value, int):
        return None
    return _ROOT_HEAD if value == 0 else value - 1


def _render_with_library(conllu: ModuleType, sentence: _ConlluSentence) -> str:
    """Render a parsed sentence to CoNLL-U text via the ``conllu`` library."""
    rows = [_library_row(token) for token in sentence.tokens]
    token_list = conllu.TokenList(rows, metadata={"text": sentence.text})
    return token_list.serialize()


def _library_row(token: _ConlluToken) -> dict[str, object]:
    """Build a ``conllu`` token mapping from a parsed token."""
    return {
        "id": token.index + 1,
        "form": token.form,
        "lemma": _library_column(token.lemma),
        "upos": _library_column(token.upos),
        "xpos": _library_column(token.xpos),
        "feats": _library_feats_column(token.feats),
        "head": _library_head_column(token.head),
        "deprel": _library_column(token.deprel),
        "deps": None,
        "misc": None,
    }


def _library_column(value: str | None) -> str | None:
    """Return an optional column value for a library token mapping."""
    return value


def _library_feats_column(feats: tuple[_Feat, ...]) -> dict[str, str] | None:
    """Return the library ``feats`` mapping for ordered feature pairs."""
    if not feats:
        return None
    return {feat.key: feat.value for feat in feats}


def _library_head_column(head: int | None) -> int | None:
    """Return the 1-based library ``head`` value for a 0-based head index."""
    if head is None:
        return None
    return 0 if head == _ROOT_HEAD else head + 1


def _parse_token_line(line: str) -> _ConlluToken | None:
    """Parse one CoNLL-U token row, skipping multiword and empty-node rows."""
    columns = line.split("\t")
    column_count = 10
    if len(columns) < column_count:
        return None
    token_id = columns[0]
    if "-" in token_id or "." in token_id:
        # skip multiword-token ranges and empty (enhanced) nodes.
        return None
    try:
        index = int(token_id) - 1
    except ValueError:
        return None
    return _ConlluToken(
        index=index,
        form=columns[1],
        lemma=_optional(columns[2]),
        upos=_optional(columns[3]),
        xpos=_optional(columns[4]),
        feats=_parse_feats(columns[5]),
        head=_parse_head(columns[6]),
        deprel=_optional(columns[7]),
    )


def _optional(value: str) -> str | None:
    """Return ``None`` for the CoNLL-U empty sentinel, else the value."""
    return None if value == _EMPTY else value


def _parse_feats(value: str) -> tuple[_Feat, ...]:
    """Parse a CoNLL-U ``FEATS`` column into ordered key/value pairs."""
    if value == _EMPTY:
        return ()
    pairs: list[_Feat] = []
    for item in value.split("|"):
        key, sep, val = item.partition("=")
        if sep:
            pairs.append(_Feat(key=key, value=val))
    return tuple(pairs)


def _parse_head(value: str) -> int | None:
    """Parse a CoNLL-U ``HEAD`` column into a 0-based head index (``-1`` root)."""
    if value == _EMPTY:
        return None
    try:
        head = int(value)
    except ValueError:
        return None
    return _ROOT_HEAD if head == 0 else head - 1


def _join_forms(tokens: list[_ConlluToken]) -> str:
    """Reconstruct sentence text by joining token forms with single spaces."""
    return " ".join(token.form for token in tokens)


def _records_from_sentence(
    sentence: _ConlluSentence,
    index: int = 0,
) -> Iterator[FragmentRecord]:
    """Yield the fragment records for the ``index``-th parsed CoNLL-U sentence.

    Parameters
    ----------
    sentence : _ConlluSentence
        The parsed sentence.
    index : int, optional
        The 0-based sentence index, which suffixes the records' local ids,
        tokenisation uuid, and expression reference so several sentences share
        one fragment without colliding. Sentence 0 keeps the unsuffixed ids.
    """
    yield FragmentRecord(
        local_id=_local_id(_EXPRESSION_LOCAL_ID, index),
        nsid=_EXPRESSION_NSID,
        value_json=_expression_json(sentence.text, index),
    )
    yield FragmentRecord(
        local_id=_local_id(_SEGMENTATION_LOCAL_ID, index),
        nsid=_SEGMENTATION_NSID,
        value_json=_segmentation_json(sentence, index),
    )
    yield from _tag_layer_records(sentence, index)
    if any(token.head is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_local_id(_DEPS_LAYER_LOCAL_ID, index),
            nsid=_ANNOTATION_NSID,
            value_json=_dependency_layer_json(sentence, index),
        )


def _expression_json(text: str, index: int) -> str:
    """Return the json for the expression record carrying the sentence text."""
    expression = Expression(
        id=_local_id(_EXPRESSION_LOCAL_ID, index),
        kind="sentence",
        createdAt=_epoch(),
        text=text,
    )
    return expression.model_dump_json()


def _segmentation_json(sentence: _ConlluSentence, index: int) -> str:
    """Return the json for the segmentation record of the sentence's tokens."""
    tokens = tuple(_segmentation_tokens(sentence))
    tokenization = Tokenization(
        kind="custom",
        uuid=Uuid(value=_tokenization_uuid(index)),
        tokens=tokens,
    )
    segmentation = Segmentation(
        createdAt=_epoch(),
        expression=_expression_ref(index),
        tokenizations=(tokenization,),
    )
    return segmentation.model_dump_json()


def _segmentation_tokens(sentence: _ConlluSentence) -> Iterator[Token]:
    """Yield segmentation tokens carrying each form's true byte offsets.

    The byte cursor walks the sentence text the same way :func:`_join_forms`
    builds it: forms separated by a single space. Each token's ``textSpan``
    therefore slices the expression text back to that token's surface form.
    """
    cursor = 0
    for position, token in enumerate(sentence.tokens):
        if position > 0:
            # account for the single space joining successive forms.
            cursor += 1
        byte_length = len(token.form.encode("utf-8"))
        yield Token(
            tokenIndex=token.index,
            text=token.form,
            textSpan=Span(byteStart=cursor, byteEnd=cursor + byte_length),
        )
        cursor += byte_length


def _tag_layer_records(
    sentence: _ConlluSentence,
    index: int,
) -> Iterator[FragmentRecord]:
    """Yield the token-tag layer records present in the sentence."""
    if any(token.upos is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_local_id(_UPOS_LAYER_LOCAL_ID, index),
            nsid=_ANNOTATION_NSID,
            value_json=_tag_layer_json(
                sentence, index, "pos", _upos_label, _feats_for_upos
            ),
        )
    if any(token.xpos is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_local_id(_XPOS_LAYER_LOCAL_ID, index),
            nsid=_ANNOTATION_NSID,
            value_json=_tag_layer_json(sentence, index, "xpos", _xpos_label, _no_feats),
        )
    if any(token.lemma is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_local_id(_LEMMA_LAYER_LOCAL_ID, index),
            nsid=_ANNOTATION_NSID,
            value_json=_tag_layer_json(
                sentence, index, "lemma", _lemma_label, _no_feats
            ),
        )


def _upos_label(token: _ConlluToken) -> str | None:
    """Return a token's ``UPOS`` label."""
    return token.upos


def _xpos_label(token: _ConlluToken) -> str | None:
    """Return a token's ``XPOS`` label."""
    return token.xpos


def _lemma_label(token: _ConlluToken) -> str | None:
    """Return a token's lemma label."""
    return token.lemma


def _feats_for_upos(token: _ConlluToken) -> FeatureMap | None:
    """Return the morphological feature map for a token's ``FEATS``, if any."""
    if not token.feats:
        return None
    entries = tuple(Feature(key=feat.key, value=feat.value) for feat in token.feats)
    return FeatureMap(entries=entries)


def _no_feats(token: _ConlluToken) -> FeatureMap | None:  # noqa: ARG001
    """Return ``None``; the layer carries no per-annotation features."""
    return None


def _tag_layer_json(
    sentence: _ConlluSentence,
    index: int,
    subkind: str,
    label_of: Callable[[_ConlluToken], str | None],
    feats_of: Callable[[_ConlluToken], FeatureMap | None],
) -> str:
    """Return the json for a token-tag layer over the sentence."""
    tokenization_uuid = _tokenization_uuid(index)
    annotations = tuple(
        Annotation(
            uuid=Uuid(value=_annotation_uuid(subkind, index, token.index)),
            anchor=Anchor(
                tokenRef=TokenRef(
                    tokenIndex=token.index,
                    tokenizationId=Uuid(value=tokenization_uuid),
                )
            ),
            tokenIndex=token.index,
            label=label_of(token),
            features=feats_of(token),
        )
        for token in sentence.tokens
        if label_of(token) is not None
    )
    layer = AnnotationLayer(
        annotations=annotations,
        createdAt=_epoch(),
        expression=_expression_ref(index),
        kind="token-tag",
        subkind=subkind,
        formalism="conll-u",
        tokenizationId=Uuid(value=tokenization_uuid),
    )
    return layer.model_dump_json()


def _dependency_layer_json(sentence: _ConlluSentence, index: int) -> str:
    """Return the json for the dependency relation layer over the sentence."""
    tokenization_uuid = _tokenization_uuid(index)
    annotations = tuple(
        Annotation(
            uuid=Uuid(value=_annotation_uuid("dep", index, token.index)),
            anchor=Anchor(
                tokenRef=TokenRef(
                    tokenIndex=token.index,
                    tokenizationId=Uuid(value=tokenization_uuid),
                )
            ),
            tokenIndex=token.index,
            headIndex=token.head,
            targetIndex=token.index,
            label=token.deprel,
        )
        for token in sentence.tokens
        if token.head is not None
    )
    layer = AnnotationLayer(
        annotations=annotations,
        createdAt=_epoch(),
        expression=_expression_ref(index),
        kind="relation",
        subkind="dependency",
        formalism="universal-dependencies",
        tokenizationId=Uuid(value=tokenization_uuid),
    )
    return layer.model_dump_json()


def _sentences_from_records(
    records: tuple[FragmentRecord, ...],
) -> tuple[_ConlluSentence, ...]:
    """Recover every parsed CoNLL-U sentence from a fragment's records.

    Records are bucketed by the sentence index their local id encodes, so a
    multi-sentence fragment recovers each sentence in order.
    """
    buckets: dict[int, list[FragmentRecord]] = {}
    for record in records:
        sentence_index = _record_sentence_index(record.local_id)
        if sentence_index is None:
            continue
        buckets.setdefault(sentence_index, []).append(record)
    return tuple(
        _sentence_from_records(tuple(buckets[index])) for index in sorted(buckets)
    )


def _record_sentence_index(local_id: str) -> int | None:
    """Return the sentence index a record's local id encodes, or ``None``."""
    for stem in (
        _EXPRESSION_LOCAL_ID,
        _SEGMENTATION_LOCAL_ID,
        _UPOS_LAYER_LOCAL_ID,
        _XPOS_LAYER_LOCAL_ID,
        _LEMMA_LAYER_LOCAL_ID,
        _DEPS_LAYER_LOCAL_ID,
    ):
        sentence_index = _sentence_index_of(local_id, stem)
        if sentence_index is not None:
            return sentence_index
    return None


def _sentence_from_records(
    records: tuple[FragmentRecord, ...],
) -> _ConlluSentence:
    """Recover a single parsed CoNLL-U sentence from one sentence's records."""
    text = ""
    forms: dict[int, str] = {}
    upos: dict[int, str] = {}
    xpos: dict[int, str] = {}
    lemma: dict[int, str] = {}
    feats: dict[int, tuple[_Feat, ...]] = {}
    heads: dict[int, int] = {}
    deprels: dict[int, str] = {}
    for record in records:
        value = json.loads(record.value_json)
        if not isinstance(value, dict):
            continue
        if _sentence_index_of(record.local_id, _EXPRESSION_LOCAL_ID) is not None:
            raw_text = value.get("text")
            if isinstance(raw_text, str):
                text = raw_text
        elif _sentence_index_of(record.local_id, _SEGMENTATION_LOCAL_ID) is not None:
            _collect_forms(value, forms)
        elif _sentence_index_of(record.local_id, _UPOS_LAYER_LOCAL_ID) is not None:
            _collect_labels(value, upos)
            _collect_feats(value, feats)
        elif _sentence_index_of(record.local_id, _XPOS_LAYER_LOCAL_ID) is not None:
            _collect_labels(value, xpos)
        elif _sentence_index_of(record.local_id, _LEMMA_LAYER_LOCAL_ID) is not None:
            _collect_labels(value, lemma)
        elif _sentence_index_of(record.local_id, _DEPS_LAYER_LOCAL_ID) is not None:
            _collect_dependencies(value, heads, deprels)
    tokens = tuple(
        _ConlluToken(
            index=index,
            form=forms[index],
            lemma=lemma.get(index),
            upos=upos.get(index),
            xpos=xpos.get(index),
            feats=feats.get(index, ()),
            head=heads.get(index),
            deprel=deprels.get(index),
        )
        for index in sorted(forms)
    )
    return _ConlluSentence(text=text, tokens=tokens)


def _collect_forms(value: dict[str, JsonValue], forms: dict[int, str]) -> None:
    """Collect token forms from a segmentation json mapping."""
    tokenizations = value.get("tokenizations")
    if not isinstance(tokenizations, list):
        return
    for tokenization in tokenizations:
        if not isinstance(tokenization, dict):
            continue
        tokens = tokenization.get("tokens")
        if not isinstance(tokens, list):
            continue
        for token in tokens:
            if not isinstance(token, dict):
                continue
            index = token.get("tokenIndex")
            form = token.get("text")
            if isinstance(index, int) and isinstance(form, str):
                forms[index] = form


def _collect_labels(value: dict[str, JsonValue], labels: dict[int, str]) -> None:
    """Collect token-indexed labels from a token-tag layer json mapping."""
    for annotation in _annotations_of(value):
        index = annotation.get("tokenIndex")
        label = annotation.get("label")
        if isinstance(index, int) and isinstance(label, str):
            labels[index] = label


def _collect_feats(
    value: dict[str, JsonValue],
    feats: dict[int, tuple[_Feat, ...]],
) -> None:
    """Collect token-indexed morphological features from a layer json mapping."""
    for annotation in _annotations_of(value):
        index = annotation.get("tokenIndex")
        if not isinstance(index, int):
            continue
        pairs = _feature_pairs(annotation.get("features"))
        if pairs:
            feats[index] = pairs


def _collect_dependencies(
    value: dict[str, JsonValue],
    heads: dict[int, int],
    deprels: dict[int, str],
) -> None:
    """Collect head indices and relation labels from a dependency layer mapping."""
    for annotation in _annotations_of(value):
        index = annotation.get("tokenIndex")
        head = annotation.get("headIndex")
        deprel = annotation.get("label")
        if isinstance(index, int) and isinstance(head, int):
            heads[index] = head
        if isinstance(index, int) and isinstance(deprel, str):
            deprels[index] = deprel


def _annotations_of(value: dict[str, JsonValue]) -> Iterator[dict[str, JsonValue]]:
    """Yield the annotation json mappings of a layer json mapping."""
    annotations = value.get("annotations")
    if not isinstance(annotations, list):
        return
    for annotation in annotations:
        if isinstance(annotation, dict):
            yield annotation


def _feature_pairs(features: JsonValue) -> tuple[_Feat, ...]:
    """Recover ordered key/value pairs from a feature-map json mapping."""
    if not isinstance(features, dict):
        return ()
    entries = features.get("entries")
    if not isinstance(entries, list):
        return ()
    pairs: list[_Feat] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        val = entry.get("value")
        if isinstance(key, str) and isinstance(val, str):
            pairs.append(_Feat(key=key, value=val))
    return tuple(pairs)


def _render_sentence(sentence: _ConlluSentence) -> str:
    """Render a parsed CoNLL-U sentence back to CoNLL-U text."""
    lines = [f"# text = {sentence.text}"]
    lines.extend(_render_token(token) for token in sentence.tokens)
    lines.append("")
    return "\n".join(lines)


def _render_token(token: _ConlluToken) -> str:
    """Render one parsed token back to a CoNLL-U token row."""
    columns = (
        str(token.index + 1),
        token.form,
        _column(token.lemma),
        _column(token.upos),
        _column(token.xpos),
        _render_feats(token.feats),
        _render_head(token.head),
        _column(token.deprel),
        _EMPTY,
        _EMPTY,
    )
    return "\t".join(columns)


def _column(value: str | None) -> str:
    """Render an optional column, defaulting an absent value to the sentinel."""
    return value if value is not None else _EMPTY


def _render_feats(feats: tuple[_Feat, ...]) -> str:
    """Render ordered feature pairs back to a CoNLL-U ``FEATS`` column."""
    if not feats:
        return _EMPTY
    return "|".join(f"{feat.key}={feat.value}" for feat in feats)


def _render_head(head: int | None) -> str:
    """Render a 0-based head index back to a 1-based CoNLL-U ``HEAD`` column."""
    if head is None:
        return _EMPTY
    return "0" if head == _ROOT_HEAD else str(head + 1)


def _epoch() -> datetime:
    """Return the deterministic epoch datetime used for generated records."""
    return datetime.fromisoformat(_EPOCH)
