"""Read CoNLL-U sentences out of Layers records.

:func:`sentences` yields one typed :class:`~lairs.conllu.model.ConlluSentence`
per sentence expression of a corpus, joining the expression with the
segmentations, alignments, and annotation layers that reference it, and
rebuilding the rows through :func:`lairs.conllu.projection.sentence_from_json`.

The source is either a loaded :class:`~lairs.data.corpus.Corpus` or a raw
record mapping from AT-URI to record JSON, such as
:meth:`lairs.store.repository.Repository.content_at` returns for a pulled
dataset. The raw mapping is the fast path: records are read as JSON and never
validated into models. A corpus's pooled models are dumped to JSON once each.

The records are indexed in one pass, grouped by the expression they reference,
so the cost is linear in the number of records. References are compared as
strings, so the same code reads published records (real AT-URIs spread over
several accounts) and locally projected ones.

Sentences come in membership order (``ordinal``) when the source holds
membership records for the selected corpus, and otherwise in source order.
Document and paragraph expressions are not sentences, but they restore the
``# newdoc`` and ``# newpar`` comments of records published without the comment
carriers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from lairs._aturi import nsid_of
from lairs.conllu.projection import (
    ALIGNMENT_NSID,
    ANNOTATION_NSID,
    EXPRESSION_NSID,
    MEMBERSHIP_NSID,
    SEGMENTATION_NSID,
    sentence_from_json,
)
from lairs.records._generated.alignment import Alignment
from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.corpus import Membership
from lairs.records._generated.expression import Expression
from lairs.records._generated.segmentation import Segmentation

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    import didactic.api as dx

    from lairs._types import JsonValue
    from lairs.conllu.model import ConlluSentence
    from lairs.conllu.projection import JsonObject
    from lairs.data.corpus import Corpus

__all__ = ["sentences", "sentences_from_json"]

# the collection of each record model the reader consumes.
_MODEL_NSIDS: tuple[tuple[type[dx.Model], str], ...] = (
    (Expression, EXPRESSION_NSID),
    (Segmentation, SEGMENTATION_NSID),
    (AnnotationLayer, ANNOTATION_NSID),
    (Alignment, ALIGNMENT_NSID),
    (Membership, MEMBERSHIP_NSID),
)

# the collections the reader consumes.
_NSIDS = frozenset(nsid for _, nsid in _MODEL_NSIDS)


class _Joined:
    """The records that reference one expression."""

    __slots__ = ("alignments", "layers", "segmentations")

    def __init__(self) -> None:
        self.segmentations: list[JsonObject] = []
        self.layers: list[JsonObject] = []
        self.alignments: list[JsonObject] = []


def sentences(
    source: Corpus | Mapping[str, JsonValue],
    *,
    corpus: str | None = None,
    split: str | None = None,
) -> Iterator[ConlluSentence]:
    """Yield the CoNLL-U sentences of a corpus, in corpus order.

    Parameters
    ----------
    source : lairs.data.corpus.Corpus or collections.abc.Mapping
        A loaded corpus, or a mapping from AT-URI to record JSON (for instance
        ``Repository.content_at(revision)``).
    corpus : str or None, optional
        The AT-URI of the corpus to read, matched against membership
        ``corpusRef``. Defaults to the corpus's own URI for a
        :class:`~lairs.data.corpus.Corpus`. When ``None`` every membership
        counts.
    split : str or None, optional
        Only yield sentences whose membership has this split (``train``,
        ``dev``, ``test``).

    Yields
    ------
    ConlluSentence
        Each sentence. A sentence rebuilt without the lossless carriers names
        its reconstructed fields in
        :attr:`~lairs.conllu.model.ConlluSentence.lossy`.
    """
    if isinstance(source, Mapping):
        return sentences_from_json(_mapping_records(source), corpus=corpus, split=split)
    selected = corpus if corpus is not None else source.uri
    return sentences_from_json(_corpus_records(source), corpus=selected, split=split)


def _mapping_records(
    source: Mapping[str, JsonValue],
) -> Iterator[tuple[str, str, JsonObject]]:
    """Yield (uri, collection, value) for the records of a raw mapping."""
    for uri, value in source.items():
        if not isinstance(value, dict):
            continue
        nsid = nsid_of(uri)
        if nsid not in _NSIDS:
            declared = value.get("$type")
            nsid = declared if isinstance(declared, str) else nsid
        yield uri, nsid, value


def _corpus_records(source: Corpus) -> Iterator[tuple[str, str, JsonObject]]:
    """Yield (uri, collection, value) for the pooled records of a corpus."""
    pool = source.pool
    for uri in pool.uris():
        model = pool.get(uri)
        if model is None:
            continue
        nsid = next((n for cls, n in _MODEL_NSIDS if isinstance(model, cls)), None)
        if nsid is None:
            continue
        value = json.loads(model.model_dump_json())
        if isinstance(value, dict):
            yield uri, nsid, value


def _str(value: JsonValue | None) -> str | None:
    """Return ``value`` when it is a string."""
    return value if isinstance(value, str) else None


def sentences_from_json(
    records: Iterable[tuple[str, str, JsonObject]],
    *,
    corpus: str | None = None,
    split: str | None = None,
) -> Iterator[ConlluSentence]:
    """Yield CoNLL-U sentences from (uri, collection, value) record triples.

    This is the core of :func:`sentences`, for callers that already hold
    record JSON in another shape. Records of other collections are ignored.

    Parameters
    ----------
    records : collections.abc.Iterable of tuple of (str, str, JsonObject)
        Each record's AT-URI, collection NSID, and JSON value.
    corpus : str or None, optional
        The corpus AT-URI memberships must reference; ``None`` accepts all.
    split : str or None, optional
        Only yield sentences whose membership has this split.

    Yields
    ------
    ConlluSentence
        Each sentence, in membership order or else source order.
    """
    expressions: dict[str, JsonObject] = {}
    joined: dict[str, _Joined] = {}
    members: list[tuple[int, int, str, str | None]] = []
    for uri, nsid, value in records:
        if nsid == EXPRESSION_NSID:
            expressions[uri] = value
            continue
        if nsid == MEMBERSHIP_NSID:
            if corpus is not None and value.get("corpusRef") != corpus:
                continue
            ref = _str(value.get("expressionRef"))
            ordinal = value.get("ordinal")
            if ref is not None:
                position = ordinal if isinstance(ordinal, int) else len(members)
                members.append((position, len(members), ref, _str(value.get("split"))))
            continue
        ref = _str(value.get("expression"))
        if ref is None:
            continue
        bucket = joined.get(ref)
        if bucket is None:
            bucket = joined[ref] = _Joined()
        if nsid == SEGMENTATION_NSID:
            bucket.segmentations.append(value)
        elif nsid == ANNOTATION_NSID:
            bucket.layers.append(value)
        elif nsid == ALIGNMENT_NSID:
            bucket.alignments.append(value)
    if members:
        members.sort()
        order = [ref for _, _, ref, slug in members if split is None or slug == split]
    elif split is None:
        order = list(expressions)
    else:
        order = []
    previous: tuple[str | None, str | None] = (None, None)
    empty = _Joined()
    for ref in order:
        expression = expressions.get(ref)
        if expression is None or expression.get("kind") != "sentence":
            continue
        units = _units(expression, expressions)
        opened = _opened(units, previous, expressions)
        previous = units
        bucket = joined.get(ref, empty)
        yield sentence_from_json(
            expression,
            bucket.segmentations,
            bucket.layers,
            bucket.alignments,
            opened=opened,
        )


def _units(
    expression: JsonObject,
    expressions: Mapping[str, JsonObject],
) -> tuple[str | None, str | None]:
    """Return the (document, paragraph) references enclosing a sentence."""
    parent_ref = _str(expression.get("parentRef"))
    parent = expressions.get(parent_ref) if parent_ref is not None else None
    if parent is None:
        return None, None
    if parent.get("kind") == "paragraph":
        return _str(parent.get("parentRef")), parent_ref
    return parent_ref, None


def _opened(
    units: tuple[str | None, str | None],
    previous: tuple[str | None, str | None],
    expressions: Mapping[str, JsonObject],
) -> list[JsonObject]:
    """Return the document and paragraph expressions a sentence opens."""
    document, paragraph = units
    opened: list[JsonObject] = []
    new_document = document is not None and document != previous[0]
    if new_document and document is not None and document in expressions:
        opened.append(expressions[document])
    if (
        paragraph is not None
        and (new_document or paragraph != previous[1])
        and paragraph in expressions
    ):
        opened.append(expressions[paragraph])
    return opened
