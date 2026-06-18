"""CoNLL-U format codec.

Converts between CoNLL-U (Universal Dependencies) and lairs records, binding to
the :class:`~lairs.integrations.ports.Codec` port. The optional ``conllu``
library (the ``lairs[conllu]`` extra) is imported lazily inside the codec
methods, with a clear error when it is missing, so importing this module never
pulls the dependency in.

The CoNLL-U surface maps onto Layers as follows:

- the ``FORM`` column of each token-line becomes a
  :class:`~lairs.records.segmentation.Token`, and a sentence's tokens become a
  :class:`~lairs.records.segmentation.Tokenization` inside one
  :class:`~lairs.records.segmentation.Segmentation` record.
- ``UPOS`` and ``XPOS`` become token-tag
  :class:`~lairs.records.annotation.AnnotationLayer` records anchored by token
  index; ``LEMMA`` becomes a token-tag lemma layer; ``FEATS`` are carried as
  per-annotation features.
- ``HEAD``/``DEPREL`` become a relation (dependency) annotation layer, with each
  arc carrying ``headIndex`` (``-1`` at the root) and ``targetIndex``.
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

    from lairs._types import JsonValue

__all__ = ["ConlluCodec", "ConlluIso"]

# the epoch timestamp used for the deterministic createdAt of generated records.
_EPOCH = "1970-01-01T00:00:00+00:00"

# the at-uri-shaped local references the generated records point at.
_EXPRESSION_REF = "at://local/expression"

# the deterministic uuid of the generated tokenization.
_TOKENIZATION_UUID = "tokenization-0"

# the nsid collections of the records a conllu fragment carries.
_EXPRESSION_NSID = "pub.layers.expression"
_SEGMENTATION_NSID = "pub.layers.segmentation"
_ANNOTATION_NSID = "pub.layers.annotation"

# the local ids of the records inside a conllu fragment.
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


def _require_conllu() -> None:
    """Import the optional ``conllu`` library or raise a clear error.

    Raises
    ------
    ModuleNotFoundError
        When the ``conllu`` library is not installed.
    """
    try:
        import conllu  # noqa: F401, PLC0415
    except ImportError as error:
        message = (
            "the conllu codec requires the optional 'conllu' library; "
            "install it with `pip install lairs[conllu]`"
        )
        raise ModuleNotFoundError(message) from error


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

        Parameters
        ----------
        src : str or bytes
            The CoNLL-U source.
        into : lairs.integrations.codecs.CorpusFragment or None, optional
            An existing fragment to extend with the decoded records.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The decoded fragment.
        """
        _require_conllu()
        sentence = _parse_conllu(_as_str(src))
        records = list(into.records) if into is not None else []
        records.extend(_records_from_sentence(sentence))
        return CorpusFragment(records=tuple(records), source=self.name)

    def encode(self, records: Iterable[FragmentRecord]) -> str:
        """Encode fragment records into CoNLL-U text.

        Parameters
        ----------
        records : collections.abc.Iterable of FragmentRecord
            The records to encode.

        Returns
        -------
        str
            The CoNLL-U representation.
        """
        _require_conllu()
        return _render_sentence(_sentence_from_records(tuple(records)))


class _Feat(dx.Model):
    """A single CoNLL-U morphological feature key/value pair.

    Parameters
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

    Parameters
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

    Parameters
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


def _records_from_sentence(sentence: _ConlluSentence) -> Iterator[FragmentRecord]:
    """Yield the fragment records for a parsed CoNLL-U sentence."""
    yield FragmentRecord(
        local_id=_EXPRESSION_LOCAL_ID,
        nsid=_EXPRESSION_NSID,
        value_json=_expression_json(sentence.text),
    )
    yield FragmentRecord(
        local_id=_SEGMENTATION_LOCAL_ID,
        nsid=_SEGMENTATION_NSID,
        value_json=_segmentation_json(sentence),
    )
    yield from _tag_layer_records(sentence)
    if any(token.head is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_DEPS_LAYER_LOCAL_ID,
            nsid=_ANNOTATION_NSID,
            value_json=_dependency_layer_json(sentence),
        )


def _expression_json(text: str) -> str:
    """Return the json for the expression record carrying the sentence text."""
    expression = Expression(
        id=_EXPRESSION_LOCAL_ID,
        kind="sentence",
        createdAt=_epoch(),
        text=text,
    )
    return expression.model_dump_json()


def _segmentation_json(sentence: _ConlluSentence) -> str:
    """Return the json for the segmentation record of the sentence's tokens."""
    tokens = tuple(_segmentation_token(token) for token in sentence.tokens)
    tokenization = Tokenization(
        kind="custom",
        uuid=Uuid(value=_TOKENIZATION_UUID),
        tokens=tokens,
    )
    segmentation = Segmentation(
        createdAt=_epoch(),
        expression=_EXPRESSION_REF,
        tokenizations=(tokenization,),
    )
    return segmentation.model_dump_json()


def _segmentation_token(token: _ConlluToken) -> Token:
    """Build a segmentation token from a parsed CoNLL-U token."""
    byte_length = len(token.form.encode("utf-8"))
    return Token(
        tokenIndex=token.index,
        text=token.form,
        textSpan=Span(byteStart=0, byteEnd=byte_length),
    )


def _tag_layer_records(sentence: _ConlluSentence) -> Iterator[FragmentRecord]:
    """Yield the token-tag layer records present in the sentence."""
    if any(token.upos is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_UPOS_LAYER_LOCAL_ID,
            nsid=_ANNOTATION_NSID,
            value_json=_tag_layer_json(sentence, "pos", _upos_label, _feats_for_upos),
        )
    if any(token.xpos is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_XPOS_LAYER_LOCAL_ID,
            nsid=_ANNOTATION_NSID,
            value_json=_tag_layer_json(sentence, "xpos", _xpos_label, _no_feats),
        )
    if any(token.lemma is not None for token in sentence.tokens):
        yield FragmentRecord(
            local_id=_LEMMA_LAYER_LOCAL_ID,
            nsid=_ANNOTATION_NSID,
            value_json=_tag_layer_json(sentence, "lemma", _lemma_label, _no_feats),
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
    subkind: str,
    label_of: Callable[[_ConlluToken], str | None],
    feats_of: Callable[[_ConlluToken], FeatureMap | None],
) -> str:
    """Return the json for a token-tag layer over the sentence."""
    annotations = tuple(
        Annotation(
            uuid=Uuid(value=f"{subkind}-{token.index}"),
            anchor=Anchor(
                tokenRef=TokenRef(
                    tokenIndex=token.index,
                    tokenizationId=Uuid(value=_TOKENIZATION_UUID),
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
        expression=_EXPRESSION_REF,
        kind="token-tag",
        subkind=subkind,
        formalism="conll-u",
        tokenizationId=Uuid(value=_TOKENIZATION_UUID),
    )
    return layer.model_dump_json()


def _dependency_layer_json(sentence: _ConlluSentence) -> str:
    """Return the json for the dependency relation layer over the sentence."""
    annotations = tuple(
        Annotation(
            uuid=Uuid(value=f"dep-{token.index}"),
            anchor=Anchor(
                tokenRef=TokenRef(
                    tokenIndex=token.index,
                    tokenizationId=Uuid(value=_TOKENIZATION_UUID),
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
        expression=_EXPRESSION_REF,
        kind="relation",
        subkind="dependency",
        formalism="universal-dependencies",
        tokenizationId=Uuid(value=_TOKENIZATION_UUID),
    )
    return layer.model_dump_json()


def _sentence_from_records(
    records: tuple[FragmentRecord, ...],
) -> _ConlluSentence:
    """Recover a parsed CoNLL-U sentence from fragment records."""
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
        if record.local_id == _EXPRESSION_LOCAL_ID:
            raw_text = value.get("text")
            if isinstance(raw_text, str):
                text = raw_text
        elif record.local_id == _SEGMENTATION_LOCAL_ID:
            _collect_forms(value, forms)
        elif record.local_id == _UPOS_LAYER_LOCAL_ID:
            _collect_labels(value, upos)
            _collect_feats(value, feats)
        elif record.local_id == _XPOS_LAYER_LOCAL_ID:
            _collect_labels(value, xpos)
        elif record.local_id == _LEMMA_LAYER_LOCAL_ID:
            _collect_labels(value, lemma)
        elif record.local_id == _DEPS_LAYER_LOCAL_ID:
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
