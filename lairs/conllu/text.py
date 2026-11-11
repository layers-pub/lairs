"""Exact CoNLL-U text input and output.

:func:`parse` streams sentences from CoNLL-U text or from any iterable of lines
(an open file, for instance), holding one sentence at a time, so a large
treebank never has to be read into memory whole. :func:`serialize` and
:func:`dump` write sentences back.

The contract is byte-exact: for well-formed CoNLL-U in canonical framing,
``serialize(parse(text)) == text``. Canonical framing means LF line endings,
each sentence followed by exactly one blank line, and no other blank lines.
Parsing normalises framing and nothing else: CRLF line endings become LF, a
leading byte-order mark is dropped, runs of blank (or whitespace-only) lines
between sentences collapse to one, and a missing final blank line is supplied.
Every comment and row line is kept verbatim.

A malformed line raises :class:`ConlluSyntaxError` naming its 1-based line
number in the source; no line is ever silently dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.conllu.model import ConlluSentence, check_row

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import TextIO

__all__ = ["ConlluSyntaxError", "dump", "parse", "serialize", "serialize_sentence"]

# the byte-order mark a file may start with.
_BOM = "﻿"


class ConlluSyntaxError(ValueError):
    """A malformed CoNLL-U line.

    Parameters
    ----------
    message : str
        What is wrong with the line.
    line : int
        The 1-based line number in the source.

    Attributes
    ----------
    line : int
        The 1-based line number in the source.
    """

    def __init__(self, message: str, line: int) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


def _lines_of(source: str | Iterable[str]) -> Iterator[str]:
    r"""Yield the lines of ``source`` without their line terminators.

    Text is split on ``\n`` only (not on the other characters
    :meth:`str.splitlines` treats as breaks, which may occur inside a FORM),
    and a ``\r`` before the ``\n`` is dropped.
    """
    lines = source.split("\n") if isinstance(source, str) else source
    for line in lines:
        yield line.removesuffix("\n").removesuffix("\r")


def parse(source: str | Iterable[str]) -> Iterator[ConlluSentence]:
    r"""Parse CoNLL-U into sentences, one at a time.

    Parameters
    ----------
    source : str or collections.abc.Iterable of str
        The CoNLL-U text, or its lines (with or without terminators), such as a
        text file. Open files with ``newline="\n"`` so a stray carriage return
        or other break character inside a column is not taken for a line end.

    Yields
    ------
    ConlluSentence
        Each sentence, in source order.

    Raises
    ------
    ConlluSyntaxError
        On the first malformed line: a row without ten non-empty columns, a
        malformed id, HEAD, FEATS, or DEPS value, a comment after a sentence's
        rows, or comments with no rows.
    """
    block: list[str] = []
    start = 0
    seen_row = False
    for number, raw in enumerate(_lines_of(source), start=1):
        line = raw.removeprefix(_BOM) if number == 1 else raw
        if not line.strip():
            if block:
                yield _sentence(block, start, seen_row=seen_row)
                block = []
                seen_row = False
            continue
        if not block:
            start = number
        if line.startswith("#"):
            if seen_row:
                message = "comment after the sentence's rows"
                raise ConlluSyntaxError(message, number)
        else:
            seen_row = True
            try:
                check_row(line)
            except ValueError as error:
                raise ConlluSyntaxError(str(error), number) from error
        block.append(line)
    if block:
        yield _sentence(block, start, seen_row=seen_row)


def _sentence(block: list[str], start: int, *, seen_row: bool) -> ConlluSentence:
    """Build a sentence from validated lines, or raise for a rowless block."""
    if not seen_row:
        message = "sentence has comments but no rows"
        raise ConlluSyntaxError(message, start + len(block) - 1)
    return ConlluSentence(block="\n".join(block))


def serialize_sentence(sentence: ConlluSentence) -> str:
    """Serialize one sentence, followed by its blank separator line.

    Parameters
    ----------
    sentence : ConlluSentence
        The sentence.

    Returns
    -------
    str
        The sentence's lines, each ending in a newline, then a blank line.
    """
    return f"{sentence.block}\n\n"


def serialize(sentences: Iterable[ConlluSentence]) -> str:
    """Serialize sentences to CoNLL-U text in canonical framing.

    Parameters
    ----------
    sentences : collections.abc.Iterable of ConlluSentence
        The sentences, in order.

    Returns
    -------
    str
        The CoNLL-U text.
    """
    return "".join(serialize_sentence(sentence) for sentence in sentences)


def dump(sentences: Iterable[ConlluSentence], handle: TextIO) -> int:
    """Write sentences to an open text file, one at a time.

    Parameters
    ----------
    sentences : collections.abc.Iterable of ConlluSentence
        The sentences, in order.
    handle : typing.TextIO
        The file to write to.

    Returns
    -------
    int
        The number of sentences written.
    """
    count = 0
    for sentence in sentences:
        handle.write(serialize_sentence(sentence))
        count += 1
    return count
