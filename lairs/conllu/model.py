"""Typed CoNLL-U sentences and rows.

A CoNLL-U sentence is a block of comment lines followed by token rows, and a
row is ten tab-separated columns. The models here keep the exact source text
of a sentence (its comment and row lines) as their stored value, and expose
typed views (:attr:`ConlluSentence.comments`, :attr:`ConlluSentence.rows`, and
on each row :attr:`ConlluRow.id`, :attr:`ConlluRow.feats`, and so on) as
cached derivations of that text.

Keeping the text as the stored value has two consequences. Serialization is
exact by construction, since nothing a parser could normalise is ever thrown
away. And reading is cheap, since a row model, its id, and its feature, arc,
and MISC models are only built when a caller reads them, while the small value
models (:class:`RowId`, :class:`Feat`, :class:`Dep`, :class:`MiscItem`) are
interned by their source text so a treebank shares one instance per distinct
value.

Every stored value is validated on construction, so a model never holds text a
CoNLL-U reader would reject. :func:`check_row` and :func:`check_block` are the
validators; :mod:`lairs.conllu.text` calls them with source line numbers.

The conventions for absent values follow the CoNLL-U specification. ``_`` in
the LEMMA, UPOS, XPOS, HEAD, DEPREL columns reads as ``None``, and in the FEATS,
DEPS, and MISC columns as an empty tuple. FORM is never absent: ``_`` there is
the literal underscore token. LEMMA ``_`` is likewise read as the literal
underscore when the FORM is ``_``, as the guidelines prescribe for the
underscore token. Writing either reading back yields ``_``, so the distinction
never changes the text.
"""

from __future__ import annotations

import functools
import re
from typing import TYPE_CHECKING, Literal

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "Comment",
    "ConlluRow",
    "ConlluSentence",
    "Dep",
    "Feat",
    "MiscItem",
    "RowId",
    "RowKind",
    "check_block",
    "check_row",
    "split_items",
]

type RowKind = Literal["word", "range", "empty"]
"""The three kinds of CoNLL-U row: a word, a multiword range, an empty node."""

# the conllu sentinel for an absent column value.
EMPTY = "_"

# the number of tab-separated columns in a token row.
COLUMNS = 10

# column positions in a token row.
ID, FORM, LEMMA, UPOS, XPOS, FEATS, HEAD, DEPREL, DEPS, MISC = range(COLUMNS)

# the valid shapes of a row id, a head, and a deps head.
_ROW_ID = re.compile(r"([1-9][0-9]*)(?:-([1-9][0-9]*))?|(0|[1-9][0-9]*)\.([1-9][0-9]*)")
_HEAD = re.compile(r"0|[1-9][0-9]*")
_DEPS_HEAD = re.compile(r"(0|[1-9][0-9]*)(?:\.([1-9][0-9]*))?")

# the bound on each interning cache; distinct values beyond it are rebuilt.
_CACHE_SIZE = 1 << 16


class RowId(dx.Model):
    """The id of a CoNLL-U row or of the head of an enhanced arc.

    A word id is a positive integer (``7``); a multiword range spans two word
    ids (``1-2``); an empty node is a word id and a positive minor index
    (``3.1``, or ``0.1`` before the first word). The root head of an arc is the
    word id ``0``.

    Attributes
    ----------
    major : int
        The word id, the first word of a range, or the word an empty node
        follows.
    end : int or None
        The last word of a range, inclusive; ``None`` for other kinds.
    minor : int or None
        The empty-node index after the dot; ``None`` for other kinds.
    """

    major: int = dx.field(description="word id, range start, or empty-node major")
    end: int | None = dx.field(default=None, description="range end, inclusive")
    minor: int | None = dx.field(default=None, description="empty-node minor index")

    @property
    def kind(self) -> RowKind:
        """Return which of the three row kinds this id names."""
        if self.end is not None:
            return "range"
        if self.minor is not None:
            return "empty"
        return "word"

    @property
    def is_word(self) -> bool:
        """Return whether this id names a word (or the root, ``0``)."""
        return self.end is None and self.minor is None

    @property
    def is_range(self) -> bool:
        """Return whether this id names a multiword range."""
        return self.end is not None

    @property
    def is_empty(self) -> bool:
        """Return whether this id names an empty node."""
        return self.minor is not None

    @property
    def text(self) -> str:
        """Return the id as CoNLL-U writes it (``7``, ``1-2``, ``3.1``)."""
        if self.end is not None:
            return f"{self.major}-{self.end}"
        if self.minor is not None:
            return f"{self.major}.{self.minor}"
        return str(self.major)

    @classmethod
    def parse(cls, text: str) -> RowId:
        """Parse a row id or a deps head from its CoNLL-U text.

        Parameters
        ----------
        text : str
            The id text (``7``, ``1-2``, ``3.1``, or ``0`` for a root head).

        Returns
        -------
        RowId
            The parsed id, shared with every other parse of the same text.

        Raises
        ------
        ValueError
            When ``text`` is not a well-formed id.
        """
        return _row_id(text)


class Feat(dx.Model):
    """One ``Name=Value`` item of a FEATS column.

    The name is kept as written, layer included (``Number[psor]``), and the
    value as written, so a multi-valued feature (``Case=Acc,Dat``) keeps its
    comma-joined values in their order.

    Attributes
    ----------
    name : str
        The feature name, with any layer suffix.
    value : str
        The value text, possibly several values joined by commas.
    """

    name: str = dx.field(description="feature name as written, with any layer")
    value: str = dx.field(description="value text, comma-joined when multi-valued")

    @property
    def feature(self) -> str:
        """Return the name without its layer (``Number[psor]`` to ``Number``)."""
        start = self.name.find("[")
        return self.name[:start] if start != -1 else self.name

    @property
    def layer(self) -> str | None:
        """Return the layer of a layered feature (``psor``), or ``None``."""
        start = self.name.find("[")
        if start == -1 or not self.name.endswith("]"):
            return None
        return self.name[start + 1 : -1]

    @property
    def values(self) -> tuple[str, ...]:
        """Return the individual values of a multi-valued feature, in order."""
        return tuple(self.value.split(","))

    @property
    def text(self) -> str:
        """Return the item as CoNLL-U writes it (``Name=Value``)."""
        return f"{self.name}={self.value}"


class Dep(dx.Model):
    """One arc of a DEPS column: a head and a relation.

    Attributes
    ----------
    head : RowId
        The head: a word id, ``0`` for the root, or an empty-node id.
    relation : str
        The enhanced relation, subtypes and case markers included
        (``obl:on``).
    """

    head: dx.Embed[RowId] = dx.field(description="the head of the arc")
    relation: str = dx.field(description="the enhanced relation")

    @property
    def text(self) -> str:
        """Return the arc as CoNLL-U writes it (``head:relation``)."""
        return f"{self.head.text}:{self.relation}"


class MiscItem(dx.Model):
    """One item of a MISC column.

    MISC items are usually ``Key=Value`` pairs, but the column is free-form:
    an item may have no ``=`` at all (a bare item), and a key may repeat. Each
    item keeps exactly what was written, so the column rebuilds verbatim.

    Attributes
    ----------
    key : str
        The text before the first ``=``, or the whole item when it has none.
    value : str or None
        The text after the first ``=``, or ``None`` for a bare item.
    """

    key: str = dx.field(description="text before the first '=', or the bare item")
    value: str | None = dx.field(default=None, description="text after the first '='")

    @property
    def text(self) -> str:
        """Return the item as CoNLL-U writes it."""
        return self.key if self.value is None else f"{self.key}={self.value}"


class Comment(dx.Model):
    """One sentence comment line.

    Attributes
    ----------
    text : str
        The line after its leading ``#``, verbatim (spacing included).
    """

    text: str = dx.field(description="the comment line after '#', verbatim")

    @property
    def key(self) -> str:
        """Return the comment's key: the stripped text before ``=``, or the whole line.

        A ``# newdoc`` marker and a free-text comment have no ``=``; their key is
        the stripped line, mirroring how CoNLL-U tools read them.
        """
        return self.text.split("=", 1)[0].strip()

    @property
    def value(self) -> str | None:
        """Return the stripped text after the first ``=``, or ``None`` when absent."""
        _, sep, value = self.text.partition("=")
        return value.strip() if sep else None

    @property
    def line(self) -> str:
        """Return the comment as CoNLL-U writes it, with its ``#``."""
        return f"#{self.text}"


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _row_id(text: str) -> RowId:
    """Return the interned :class:`RowId` for an id or deps-head text."""
    if text == "0":
        return RowId(major=0)
    match = _ROW_ID.fullmatch(text)
    if match is None:
        message = f"malformed id {text!r}"
        raise ValueError(message)
    word, end, empty_major, minor = match.groups()
    if word is not None:
        return RowId(major=int(word), end=int(end) if end is not None else None)
    return RowId(major=int(empty_major), minor=int(minor))


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _feat(text: str) -> Feat:
    """Return the interned :class:`Feat` for one FEATS item."""
    name, _, value = text.partition("=")
    return Feat(name=name, value=value)


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _dep(text: str) -> Dep:
    """Return the interned :class:`Dep` for one DEPS item."""
    head, _, relation = text.partition(":")
    return Dep(head=_row_id(head), relation=relation)


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _misc_item(text: str) -> MiscItem:
    """Return the interned :class:`MiscItem` for one MISC item."""
    key, sep, value = text.partition("=")
    return MiscItem(key=key, value=value if sep else None)


def split_items(column: str) -> tuple[str, ...]:
    """Split a FEATS, DEPS, or MISC column into its ``|``-separated items.

    Parameters
    ----------
    column : str
        The raw column text.

    Returns
    -------
    tuple of str
        The items, or an empty tuple for the absent value ``_``.
    """
    if column == EMPTY:
        return ()
    return tuple(column.split("|"))


def check_row(line: str) -> tuple[str, ...]:
    """Validate one token row and return its ten columns.

    The checks cover what a reader needs to interpret the row: ten non-empty
    tab-separated columns, a well-formed id, a HEAD that is ``_`` or a word
    id, FEATS items of the form ``Name=Value``, and DEPS items of the form
    ``head:relation``. Column contents are otherwise free, as in CoNLL-U.

    Parameters
    ----------
    line : str
        The row text, without its newline.

    Returns
    -------
    tuple of str
        The ten columns.

    Raises
    ------
    ValueError
        When the row is malformed; the message names the problem.
    """
    columns = tuple(line.split("\t"))
    if len(columns) != COLUMNS:
        message = f"expected {COLUMNS} tab-separated columns, found {len(columns)}"
        raise ValueError(message)
    for position, column in enumerate(columns):
        if not column:
            message = f"column {position + 1} is empty (use '_' for no value)"
            raise ValueError(message)
    if _ROW_ID.fullmatch(columns[ID]) is None:
        message = f"malformed id {columns[ID]!r}"
        raise ValueError(message)
    head = columns[HEAD]
    if head != EMPTY and _HEAD.fullmatch(head) is None:
        message = f"malformed HEAD {head!r}"
        raise ValueError(message)
    for item in split_items(columns[FEATS]):
        name, sep, value = item.partition("=")
        if not sep or not name or not value:
            message = f"malformed FEATS item {item!r} (expected Name=Value)"
            raise ValueError(message)
    for item in split_items(columns[DEPS]):
        dep_head, sep, relation = item.partition(":")
        if not sep or not relation or _DEPS_HEAD.fullmatch(dep_head) is None:
            message = f"malformed DEPS item {item!r} (expected head:relation)"
            raise ValueError(message)
    return columns


def check_block(block: str) -> int:
    """Validate a sentence block and return the line offset of its first row.

    A block is the comment lines of one sentence followed by its token rows,
    joined by newlines, with no blank line. Comments must precede the rows,
    and a sentence must have at least one row.

    Parameters
    ----------
    block : str
        The sentence block.

    Returns
    -------
    int
        The 0-based index of the first row line within the block.

    Raises
    ------
    ValueError
        When the block is malformed. The message starts with the 1-based line
        number within the block, as ``line N: ...``.
    """
    lines = block.split("\n")
    first_row: int | None = None
    for index, line in enumerate(lines):
        number = index + 1
        if not line.strip():
            message = f"line {number}: blank line inside a sentence"
            raise ValueError(message)
        if line.startswith("#"):
            if first_row is not None:
                message = f"line {number}: comment after the sentence's rows"
                raise ValueError(message)
            continue
        if first_row is None:
            first_row = index
        try:
            check_row(line)
        except ValueError as error:
            message = f"line {number}: {error}"
            raise ValueError(message) from error
    if first_row is None:
        message = f"line {len(lines)}: sentence has comments but no rows"
        raise ValueError(message)
    return first_row


def _checked_row[T](line: T) -> str:
    """Validate a row line for the :class:`ConlluRow` field converter."""
    if not isinstance(line, str):
        message = "a row line must be a string"
        raise TypeError(message)
    check_row(line)
    return line


def _checked_block[T](block: T) -> str:
    """Validate a sentence block for the :class:`ConlluSentence` field converter."""
    if not isinstance(block, str):
        message = "a sentence block must be a string"
        raise TypeError(message)
    check_block(block)
    return block


def _optional(column: str) -> str | None:
    """Return ``None`` for the absent value ``_``, else the column."""
    return None if column == EMPTY else column


def _column(value: str | None) -> str:
    """Render an optional column value, writing ``_`` for ``None``."""
    return EMPTY if value is None else value


def _items_column(items: Iterable[str]) -> str:
    """Join item texts into a ``|``-separated column, or ``_`` when empty."""
    joined = "|".join(items)
    return joined or EMPTY


class ConlluRow(dx.Model):
    """One token row: a word, a multiword range, or an empty node.

    The stored value is the row's exact text; every column is a typed view of
    it. Build a row from typed values with :meth:`build`.

    Attributes
    ----------
    line : str
        The row's ten tab-separated columns, without a newline.
    """

    line: str = dx.field(
        description="the row's ten tab-separated columns, verbatim",
        converter=_checked_row,
    )

    @dx.derived
    def columns(self) -> tuple[str, ...]:
        """Return the ten raw column texts."""
        return tuple(self.line.split("\t"))

    @dx.derived
    def id(self) -> RowId:
        """Return the row id (word, range, or empty node)."""
        return _row_id(self.columns[ID])

    @property
    def kind(self) -> RowKind:
        """Return the row's kind: ``word``, ``range``, or ``empty``."""
        return self.id.kind

    @property
    def form(self) -> str:
        """Return FORM; ``_`` is the literal underscore token."""
        return self.columns[FORM]

    @property
    def lemma(self) -> str | None:
        """Return LEMMA, or ``None`` when absent.

        ``_`` reads as the literal underscore when FORM is ``_``, and as absent
        otherwise.
        """
        lemma = self.columns[LEMMA]
        if lemma == EMPTY and self.columns[FORM] != EMPTY:
            return None
        return lemma

    @property
    def upos(self) -> str | None:
        """Return UPOS, or ``None`` when absent."""
        return _optional(self.columns[UPOS])

    @property
    def xpos(self) -> str | None:
        """Return XPOS, or ``None`` when absent."""
        return _optional(self.columns[XPOS])

    @dx.derived
    def feats(self) -> tuple[Feat, ...]:
        """Return the FEATS items in source order (empty when absent)."""
        return tuple(_feat(item) for item in split_items(self.columns[FEATS]))

    @property
    def head(self) -> int | None:
        """Return HEAD (``0`` for the root), or ``None`` when absent."""
        head = self.columns[HEAD]
        return None if head == EMPTY else int(head)

    @property
    def deprel(self) -> str | None:
        """Return DEPREL, or ``None`` when absent."""
        return _optional(self.columns[DEPREL])

    @dx.derived
    def deps(self) -> tuple[Dep, ...]:
        """Return the DEPS arcs in source order (empty when absent)."""
        return tuple(_dep(item) for item in split_items(self.columns[DEPS]))

    @dx.derived
    def misc(self) -> tuple[MiscItem, ...]:
        """Return the MISC items in source order (empty when absent)."""
        return tuple(_misc_item(item) for item in split_items(self.columns[MISC]))

    def misc_value(self, key: str) -> str | None:
        """Return the value of the first MISC item with ``key``, if any.

        Parameters
        ----------
        key : str
            The MISC key (for example ``"SpaceAfter"``).

        Returns
        -------
        str or None
            The value, or ``None`` when no item has that key or it is bare.
        """
        for item in self.misc:
            if item.key == key:
                return item.value
        return None

    @classmethod
    def build(  # noqa: PLR0913  (one keyword per CoNLL-U column)
        cls,
        id: RowId | str,  # noqa: A002  (the CoNLL-U column name)
        form: str,
        *,
        lemma: str | None = None,
        upos: str | None = None,
        xpos: str | None = None,
        feats: Iterable[Feat] = (),
        head: int | None = None,
        deprel: str | None = None,
        deps: Iterable[Dep] = (),
        misc: Iterable[MiscItem] = (),
    ) -> ConlluRow:
        """Build a row from typed column values.

        Parameters
        ----------
        id : RowId or str
            The row id.
        form : str
            FORM.
        lemma, upos, xpos, deprel : str or None, optional
            The optional string columns; ``None`` writes ``_``.
        feats : collections.abc.Iterable of Feat, optional
            The FEATS items, in order.
        head : int or None, optional
            HEAD; ``None`` writes ``_``.
        deps : collections.abc.Iterable of Dep, optional
            The DEPS arcs, in order.
        misc : collections.abc.Iterable of MiscItem, optional
            The MISC items, in order.

        Returns
        -------
        ConlluRow
            The row.

        Raises
        ------
        didactic.api.ValidationError
            When the values do not make a well-formed row.
        """
        columns = (
            id.text if isinstance(id, RowId) else id,
            form,
            _column(lemma),
            _column(upos),
            _column(xpos),
            _items_column(feat.text for feat in feats),
            _column(None if head is None else str(head)),
            _column(deprel),
            _items_column(dep.text for dep in deps),
            _items_column(item.text for item in misc),
        )
        return cls(line="\t".join(columns))


class ConlluSentence(dx.Model):
    """One CoNLL-U sentence: its comments and its rows.

    The stored value is the sentence's exact block of comment and row lines;
    the comments, the rows, and the ``sent_id`` and ``text`` comment values are
    typed views of it. Build a sentence from typed parts with :meth:`build`.

    A sentence rebuilt from Layers records may not be exact, when the records
    lack the information to restore some fields. :attr:`lossy` then names the
    fields that were reconstructed rather than restored (see
    :mod:`lairs.conllu.projection`); it is empty for a parsed sentence.

    Attributes
    ----------
    block : str
        The comment lines and row lines, joined by newlines, with no trailing
        newline.
    lossy : tuple of str
        The fields that were reconstructed rather than restored exactly.
    """

    block: str = dx.field(
        description="the sentence's comment and row lines, verbatim",
        converter=_checked_block,
    )
    lossy: tuple[str, ...] = dx.field(
        default=(),
        description="fields reconstructed rather than restored exactly",
    )

    @dx.derived
    def lines(self) -> tuple[str, ...]:
        """Return every line of the block, comments first."""
        return tuple(self.block.split("\n"))

    @dx.derived
    def comment_lines(self) -> tuple[str, ...]:
        """Return the comment lines, each with its leading ``#``."""
        return tuple(line for line in self.lines if line.startswith("#"))

    @dx.derived
    def row_lines(self) -> tuple[str, ...]:
        """Return the row lines, in source order."""
        return self.lines[len(self.comment_lines) :]

    @dx.derived
    def comments(self) -> tuple[Comment, ...]:
        """Return the comments in source order."""
        return tuple(Comment(text=line[1:]) for line in self.comment_lines)

    @dx.derived
    def rows(self) -> tuple[ConlluRow, ...]:
        """Return the rows (words, multiword ranges, empty nodes) in source order."""
        return tuple(ConlluRow(line=line) for line in self.row_lines)

    @property
    def words(self) -> tuple[ConlluRow, ...]:
        """Return the word rows only, in order."""
        return tuple(row for row in self.rows if row.id.is_word)

    @property
    def exact(self) -> bool:
        """Return whether every field is exact (nothing was reconstructed)."""
        return not self.lossy

    def comment(self, key: str) -> str | None:
        """Return the value of the first ``# key = value`` comment, if any.

        Parameters
        ----------
        key : str
            The comment key (for example ``"sent_id"``).

        Returns
        -------
        str or None
            The stripped value, or ``None`` when no comment has that key.
        """
        for line in self.comment_lines:
            name, sep, value = line[1:].partition("=")
            if sep and name.strip() == key:
                return value.strip()
        return None

    @property
    def sent_id(self) -> str | None:
        """Return the ``# sent_id`` value, or ``None`` when the sentence has none."""
        return self.comment("sent_id")

    @property
    def text(self) -> str | None:
        """Return the ``# text`` value, or ``None`` when the sentence has none."""
        return self.comment("text")

    @classmethod
    def build(
        cls,
        comments: Iterable[Comment | str],
        rows: Iterable[ConlluRow | str],
        *,
        lossy: Iterable[str] = (),
    ) -> ConlluSentence:
        """Build a sentence from comments and rows.

        Parameters
        ----------
        comments : collections.abc.Iterable of Comment or str
            The comments in order. A string is a whole comment line, ``#``
            included.
        rows : collections.abc.Iterable of ConlluRow or str
            The rows in order. A string is a whole row line.
        lossy : collections.abc.Iterable of str, optional
            The fields that were reconstructed rather than restored exactly.

        Returns
        -------
        ConlluSentence
            The sentence.

        Raises
        ------
        didactic.api.ValidationError
            When the parts do not make a well-formed sentence.
        """
        lines = [c.line if isinstance(c, Comment) else c for c in comments]
        lines.extend(r.line if isinstance(r, ConlluRow) else r for r in rows)
        return cls(block="\n".join(lines), lossy=tuple(lossy))
