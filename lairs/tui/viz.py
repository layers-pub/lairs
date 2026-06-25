"""Model-driven visualizers for Layers annotations, judgments, and structure.

Everything here dispatches on the lexicon's own type system, not on any dataset:
annotation `kind`/`subkind`/`anchor`, judgment `taskType`, graph `nodeType`/
`edgeType`. The four reference corpora only exercise some paths; a conforming
record of any provenance renders through the same dispatch, with `custom` and
URI-valued slots degrading to a faithful generic view.

Renderings are monospace text (wrapped in fenced code blocks by the caller's
view layer) following established text-mode conventions: CoNLL-U token grids,
indented and arc dependency trees, bracketed constituency trees, brat-style span
lanes, ELAN-style tier timelines, Penman-ish graph edges, and sparkline /
diverging-bar / number-line judgment distributions.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from lairs._types import JsonValue
    from lairs.tui.browse import RepoBrowser

__all__ = [
    "Syntax",
    "Token",
    "alignment_bitext",
    "anchor_byte_span",
    "anchor_summary",
    "anchor_time_span",
    "anchor_token_indexes",
    "assemble_syntax",
    "conllu_grid",
    "dependency_tree",
    "document_tags",
    "feature_map",
    "graph_edges",
    "interlinear",
    "judgment_distribution",
    "layers_of",
    "segmentation_tokens",
    "single_dep_syntax",
    "span_layer_overlay",
    "span_overlay",
    "tier_timeline",
    "token_tag_interlinear",
    "tokenizations_of",
]

_ROOT = -1


# ---- small JSON accessors (kept local so this module has no view deps) -----


def _obj(value: JsonValue) -> Mapping[str, JsonValue]:
    """Return a value as a mapping, or an empty mapping otherwise."""
    return value if isinstance(value, dict) else {}


def _items(value: JsonValue) -> list[JsonValue]:
    """Return a value as a list, or an empty list otherwise."""
    return value if isinstance(value, list) else []


def _str(value: JsonValue) -> str:
    """Render a JSON scalar to a compact display string."""
    return "" if value is None else str(value)


def _short_uri(value: JsonValue) -> str:
    """Shorten an AT-URI to ``<collection-tail>/<rkey>``."""
    text = _str(value)
    if not text.startswith("at://"):
        return text
    parts = text.split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else text  # noqa: PLR2004


def _truncate(text: str, limit: int) -> str:
    """Truncate text to a limit with an ellipsis."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def feature_map(value: JsonValue) -> dict[str, str]:
    """Flatten a ``featureMap`` (``{entries:[{key,value}]}``) to a dict."""
    out: dict[str, str] = {}
    for entry in _items(_obj(value).get("entries")):
        body = _obj(entry)
        out[_str(body.get("key"))] = _str(body.get("value"))
    return out


def _fence(body: str, lang: str = "text") -> str:
    """Wrap monospace body in a fenced code block to preserve alignment."""
    return f"```{lang}\n{body}\n```"


def _uuid(value: JsonValue) -> str:
    """Return the string value of a ``{value: ...}`` uuid wrapper."""
    return _str(_obj(value).get("value"))


# ---- anchor resolution (over the full anchor union) -----------------------


def anchor_token_indexes(anchor: JsonValue) -> list[int]:
    """Return the token indexes an anchor references.

    Handles ``tokenRef`` (single) and ``tokenRefSequence`` (possibly
    non-contiguous); other anchor variants reference no tokens.
    """
    body = _obj(anchor)
    single = _obj(body.get("tokenRef")).get("tokenIndex")
    if isinstance(single, int):
        return [single]
    sequence = _obj(body.get("tokenRefSequence"))
    return [
        value
        for value in _items(sequence.get("tokenIndexes"))
        if isinstance(value, int)
    ]


def anchor_tokenization(anchor: JsonValue) -> str:
    """Return the tokenization id a token anchor refers to, or ``""``."""
    body = _obj(anchor)
    for key in ("tokenRef", "tokenRefSequence"):
        ref = _obj(body.get(key))
        if ref:
            return _uuid(ref.get("tokenizationId"))
    return ""


def anchor_byte_span(anchor: JsonValue) -> tuple[int, int] | None:
    """Return the ``(byteStart, byteEnd)`` of a text or page anchor, or None."""
    body = _obj(anchor)
    span = _obj(body.get("textSpan")) or _obj(
        _obj(body.get("pageAnchor")).get("textSpan")
    )
    start, end = span.get("byteStart"), span.get("byteEnd")
    if isinstance(start, int) and isinstance(end, int):
        return start, end
    return None


def anchor_time_span(anchor: JsonValue) -> tuple[int, int] | None:
    """Return the ``(start_ms, end_ms)`` of a temporal anchor, or None."""
    body = _obj(anchor)
    span = _obj(body.get("temporalSpan")) or _obj(
        _obj(body.get("spatioTemporalAnchor")).get("temporalSpan")
    )
    start, end = span.get("start"), span.get("ending")
    if isinstance(start, int) and isinstance(end, int):
        return start, end
    return None


def anchor_summary(anchor: JsonValue) -> str:
    """Return a one-line human descriptor of any anchor variant."""
    body = _obj(anchor)
    tokens = anchor_token_indexes(anchor)
    if tokens:
        shown = ",".join(str(i) for i in tokens[:8]) + ("…" if len(tokens) > 8 else "")  # noqa: PLR2004
        return f"token {shown}"
    byte_span = anchor_byte_span(anchor)
    if byte_span is not None:
        return f"bytes {byte_span[0]}..{byte_span[1]}"
    time_span = anchor_time_span(anchor)
    if time_span is not None:
        return f"{time_span[0] / 1000:.2f}..{time_span[1] / 1000:.2f}s"
    if body.get("pageAnchor"):
        return f"page {_str(_obj(body.get('pageAnchor')).get('page'))}"
    if body.get("externalTarget"):
        return f"external {_str(_obj(body.get('externalTarget')).get('source'))}"
    return "(no anchor)"


# ---- token model assembly --------------------------------------------------


class Token:
    """One token with its surface form and offsets within an expression."""

    __slots__ = ("byte_end", "byte_start", "index", "text")

    def __init__(self, index: int, text: str, byte_start: int, byte_end: int) -> None:
        self.index = index
        self.text = text
        self.byte_start = byte_start
        self.byte_end = byte_end


def tokenizations_of(browser: RepoBrowser, expr_uri: str) -> dict[str, list[Token]]:
    """Return ``tokenizationId -> ordered tokens`` for an expression.

    Reads every segmentation whose ``expression`` is this expression; a token's
    surface comes from its ``text`` when present, else from slicing the
    expression text by the token's ``textSpan`` byte offsets.
    """
    nsid_seg = "pub.layers.segmentation.segmentation"
    expr_text = _str(_obj(browser.load_raw(expr_uri)).get("text"))
    raw_bytes = expr_text.encode("utf-8")
    out: dict[str, list[Token]] = {}
    for _, seg in browser.related_raw(nsid_seg, "expression", expr_uri):
        for tok in _items(seg.get("tokenizations")):
            body = _obj(tok)
            tok_id = _uuid(body.get("uuid"))
            tokens: list[Token] = []
            for raw_tok in _items(body.get("tokens")):
                entry = _obj(raw_tok)
                index = entry.get("tokenIndex")
                if not isinstance(index, int):
                    continue
                span = _obj(entry.get("textSpan"))
                start = span.get("byteStart")
                end = span.get("byteEnd")
                start_i = start if isinstance(start, int) else 0
                end_i = end if isinstance(end, int) else 0
                surface = _str(entry.get("text"))
                if not surface and isinstance(start, int) and isinstance(end, int):
                    surface = raw_bytes[start:end].decode("utf-8", "replace")
                tokens.append(Token(index, surface, start_i, end_i))
            tokens.sort(key=lambda t: t.index)
            out[tok_id] = tokens
    return out


def layers_of(
    browser: RepoBrowser, expr_uri: str
) -> list[tuple[str, Mapping[str, JsonValue]]]:
    """Return the annotation layers anchored to an expression."""
    nsid = "pub.layers.annotation.annotationLayer"
    return browser.related_raw(nsid, "expression", expr_uri)


def _layer_tokenization(layer: Mapping[str, JsonValue]) -> str:
    """Return the tokenization id a layer's annotations index into."""
    declared = _uuid(layer.get("tokenizationId"))
    if declared:
        return declared
    for ann in _items(layer.get("annotations")):
        tok_id = anchor_tokenization(_obj(ann).get("anchor"))
        if tok_id:
            return tok_id
    return ""


def _pick_tokenization(
    tokenizations: Mapping[str, list[Token]],
    layers: Iterable[Mapping[str, JsonValue]],
) -> str:
    """Return the tokenization id most layers anchor into, else the longest."""
    votes: dict[str, int] = {}
    for layer in layers:
        tok_id = _layer_tokenization(layer)
        if tok_id in tokenizations:
            votes[tok_id] = votes.get(tok_id, 0) + 1
    if votes:
        return max(votes, key=lambda k: votes[k])
    if tokenizations:
        return max(tokenizations, key=lambda k: len(tokenizations[k]))
    return ""


# ---- primitives: bars, sparklines, number lines ----------------------------

_SPARK = "▁▂▃▄▅▆▇█"
_BAR = "█"


def sparkline(counts: Sequence[float]) -> str:
    """Render a sequence of magnitudes as an eight-level block sparkline."""
    if not counts:
        return ""
    peak = max(counts)
    if peak <= 0:
        return _SPARK[0] * len(counts)
    return "".join(_SPARK[min(7, round(value / peak * 7))] for value in counts)


def hbar(value: float, peak: float, width: int = 24) -> str:
    """Render a horizontal bar of ``value`` scaled against ``peak``."""
    if peak <= 0:
        return ""
    return _BAR * round(value / peak * width)


def _pct(part: float, whole: float) -> str:
    """Render ``part/whole`` as a percentage string."""
    return f"{100 * part / whole:.0f}%" if whole else "0%"


# ---- segmentation ----------------------------------------------------------


def segmentation_tokens(browser: RepoBrowser, data: Mapping[str, JsonValue]) -> str:
    """Render a segmentation as a readable token table per tokenization."""
    expr_uri = _str(data.get("expression"))
    text = _str(_obj(browser.load_raw(expr_uri)).get("text"))
    lines: list[str] = []
    if text:
        lines += [_truncate(text, 600), ""]
    for tok in _items(data.get("tokenizations")):
        body = _obj(tok)
        tokens = _items(body.get("tokens"))
        kind = _str(body.get("kind"))
        tok_id = _short_uri(_uuid(body.get("uuid"))) or _uuid(body.get("uuid"))
        lines.append(f"## {tok_id or 'tokenization'}  ({kind}, {len(tokens)} tokens)")
        rows = ["  #  token            bytes"]
        for raw_tok in tokens[:400]:
            entry = _obj(raw_tok)
            span = _obj(entry.get("textSpan"))
            byte_range = f"{_str(span.get('byteStart'))}..{_str(span.get('byteEnd'))}"
            surface = _truncate(_str(entry.get("text")), 16)
            rows.append(
                f"  {_str(entry.get('tokenIndex')):>3}  {surface:<16} {byte_range}"
            )
        lines.append(_fence("\n".join(rows)))
    if not data.get("tokenizations"):
        lines.append("*No tokenizations.*")
    return "\n".join(lines)


# ---- token-tag / dependency assembly ---------------------------------------

# token-tag subkind -> a short column header for the CoNLL-U style grid.
_TAG_COLUMN = {
    "pos": "UPOS",
    "upos": "UPOS",
    "xpos": "XPOS",
    "lemma": "LEMMA",
    "morph": "FEATS",
    "ner": "NER",
    "supersense": "SST",
    "sense": "SENSE",
    "gloss": "GLOSS",
    "phonetic": "IPA",
    "language-id": "LANG",
    "sentiment": "SENT",
    "speaker": "SPKR",
}
_DEP_SUBKINDS = ("dependency", "enhanced-dependency")


def _ann_token_index(ann: Mapping[str, JsonValue]) -> int | None:
    """Return the single token index an annotation attaches to, if any."""
    anchored = anchor_token_indexes(ann.get("anchor"))
    if anchored:
        return anchored[0]
    for key in ("tokenIndex", "targetIndex"):
        value = ann.get(key)
        if isinstance(value, int):
            return value
    return None


def _tag_column(layer: Mapping[str, JsonValue]) -> str:
    """Return the grid column header for a token-tag layer."""
    subkind = _str(layer.get("subkind"))
    fallback = (subkind or _str(layer.get("kind")) or "TAG").upper()
    return _TAG_COLUMN.get(subkind, fallback)


def _tag_values(layer: Mapping[str, JsonValue]) -> dict[int, str]:
    """Return ``tokenIndex -> value`` for a token-tag layer.

    A token with several annotations (morphological feature bundles) joins them
    with ``|`` in sorted order; otherwise the value is the annotation's ``value``
    if present, else its ``label``.
    """
    groups: dict[int, list[str]] = {}
    for raw in _items(layer.get("annotations")):
        ann = _obj(raw)
        index = _ann_token_index(ann)
        if index is None:
            continue
        value = _str(ann.get("value")) or _str(ann.get("label"))
        if value:
            groups.setdefault(index, []).append(value)
    return {
        index: ("|".join(sorted(values)) if len(values) > 1 else values[0])
        for index, values in groups.items()
    }


def _dep_relations(layer: Mapping[str, JsonValue]) -> dict[int, tuple[int, str]]:
    """Return ``dependentIndex -> (headIndex, deprel)`` for a relation layer."""
    out: dict[int, tuple[int, str]] = {}
    for raw in _items(layer.get("annotations")):
        ann = _obj(raw)
        index = _ann_token_index(ann)
        if index is None:
            continue
        head = ann.get("headIndex")
        head_i = head if isinstance(head, int) else _ROOT
        out[index] = (head_i, _str(ann.get("label")))
    return out


class Syntax:
    """The token-aligned annotations assembled over one tokenization."""

    __slots__ = ("columns", "deps", "tags", "tokenization", "tokens")

    def __init__(
        self,
        tokens: list[Token],
        columns: list[str],
        tags: dict[str, dict[int, str]],
        deps: dict[int, tuple[int, str]],
        tokenization: str,
    ) -> None:
        self.tokens = tokens
        self.columns = columns
        self.tags = tags
        self.deps = deps
        self.tokenization = tokenization


def assemble_syntax(browser: RepoBrowser, expr_uri: str) -> Syntax | None:
    """Assemble token-tag and dependency layers over an expression's tokens.

    Returns ``None`` when the expression has no tokenization to anchor into.
    """
    tokenizations = tokenizations_of(browser, expr_uri)
    layers = [layer for _, layer in layers_of(browser, expr_uri)]
    tok_id = _pick_tokenization(tokenizations, layers)
    tokens = tokenizations.get(tok_id, [])
    if not tokens:
        return None
    columns: list[str] = []
    tags: dict[str, dict[int, str]] = {}
    deps: dict[int, tuple[int, str]] = {}
    for layer in layers:
        if _layer_tokenization(layer) not in ("", tok_id):
            continue
        kind = _str(layer.get("kind"))
        subkind = _str(layer.get("subkind"))
        if kind == "token-tag":
            column = _tag_column(layer)
            values = _tag_values(layer)
            if values:
                tags.setdefault(column, {}).update(values)
                if column not in columns:
                    columns.append(column)
        elif kind in ("relation", "tree") and subkind in _DEP_SUBKINDS and not deps:
            deps = _dep_relations(layer)
    columns.sort(key=_column_order)
    return Syntax(tokens, columns, tags, deps, tok_id)


def single_dep_syntax(
    browser: RepoBrowser, expr_uri: str, layer: Mapping[str, JsonValue]
) -> Syntax | None:
    """Assemble a Syntax holding just one dependency layer's relations."""
    tok_id = _layer_tokenization(layer)
    tokens = tokenizations_of(browser, expr_uri).get(tok_id, [])
    if not tokens:
        return None
    return Syntax(tokens, [], {}, _dep_relations(layer), tok_id)


def token_tag_interlinear(
    browser: RepoBrowser, expr_uri: str, layer: Mapping[str, JsonValue]
) -> str:
    """Render a single token-tag layer as an interlinear strip over the tokens."""
    tokens = tokenizations_of(browser, expr_uri).get(_layer_tokenization(layer), [])
    if not tokens:
        return _fence("(no tokens)")
    return interlinear(tokens, [(_tag_column(layer), _tag_values(layer))])


_COLUMN_RANK = {"UPOS": 0, "XPOS": 1, "LEMMA": 2, "FEATS": 9}


def _column_order(column: str) -> tuple[int, str]:
    """Sort tag columns into a familiar CoNLL-U order, extras alphabetical."""
    return (_COLUMN_RANK.get(column, 5), column)


def conllu_grid(syntax: Syntax) -> str:
    """Render the token-aligned tags and dependencies as a CoNLL-U style grid."""
    has_dep = bool(syntax.deps)
    headers = ["#", "FORM", *syntax.columns]
    if has_dep:
        headers += ["HEAD", "DEPREL"]
    rows = [headers]
    for tok in syntax.tokens:
        cells = [str(tok.index), tok.text or "_"]
        cells += [
            syntax.tags.get(col, {}).get(tok.index, "_") for col in syntax.columns
        ]
        if has_dep:
            head, deprel = syntax.deps.get(tok.index, (_ROOT, ""))
            cells += ["0" if head < 0 else str(head), deprel or "_"]
        rows.append(cells)
    return _fence(_align_table(rows))


def _align_table(rows: list[list[str]], gap: int = 2) -> str:
    """Left-align a row-major table into fixed-width columns."""
    if not rows:
        return ""
    width = [0] * max(len(row) for row in rows)
    for row in rows:
        for col, cell in enumerate(row):
            width[col] = max(width[col], len(cell))
    spacer = " " * gap
    return "\n".join(
        spacer.join(cell.ljust(width[col]) for col, cell in enumerate(row)).rstrip()
        for row in rows
    )


def dependency_tree(syntax: Syntax) -> str:
    """Render dependencies as an indented head-to-dependent tree."""
    children: dict[int, list[int]] = {}
    roots: list[int] = []
    for tok in syntax.tokens:
        head, _ = syntax.deps.get(tok.index, (_ROOT, ""))
        if head < 0 or head == tok.index or head >= len(syntax.tokens):
            roots.append(tok.index)
        else:
            children.setdefault(head, []).append(tok.index)
    surface = {tok.index: tok.text for tok in syntax.tokens}
    lines: list[str] = []

    def walk(index: int, prefix: str, *, last: bool) -> None:
        _, deprel = syntax.deps.get(index, (_ROOT, "root"))
        connector = "└─ " if last else "├─ "
        head_label = f"{surface.get(index, '?')}  ({deprel or 'root'})"
        lines.append(
            f"{prefix}{connector}{head_label}" if prefix or lines else head_label
        )
        kids = children.get(index, [])
        child_prefix = prefix + ("   " if last else "│  ")
        for position, child in enumerate(kids):
            walk(child, child_prefix, last=position == len(kids) - 1)

    for position, root in enumerate(roots):
        walk(root, "", last=position == len(roots) - 1)
    return _fence("\n".join(lines))


def _pack_lanes(spans: list[tuple[int, int]]) -> list[int]:
    """Assign each ``(low, high)`` span a lane so overlapping spans differ.

    Shorter spans take inner lanes (nearer the tokens), matching the convention
    that nesting depth grows outward.
    """
    order = sorted(
        range(len(spans)), key=lambda i: (spans[i][1] - spans[i][0], spans[i][0])
    )
    lane_of = [0] * len(spans)
    lane_spans: list[list[tuple[int, int]]] = []
    for i in order:
        low, high = spans[i]
        placed = False
        for lane, occupants in enumerate(lane_spans):
            if all(high <= o_low or low >= o_high for o_low, o_high in occupants):
                occupants.append((low, high))
                lane_of[i] = lane
                placed = True
                break
        if not placed:
            lane_of[i] = len(lane_spans)
            lane_spans.append([(low, high)])
    return lane_of


def interlinear(tokens: list[Token], rows: list[tuple[str, dict[int, str]]]) -> str:
    """Render token-tag layers as interlinear rows beneath each token.

    ``rows`` is ordered ``(row_label, {tokenIndex: value})`` pairs; columns align
    on token index and wrap to a readable width, the classic Leipzig layout.
    """
    if not tokens:
        return _fence("(no tokens)")
    cells: list[list[str]] = []
    for tok in tokens:
        column = [tok.text or "_"]
        column += [values.get(tok.index, "") for _, values in rows]
        cells.append(column)
    label_w = max((len(label) for label, _ in rows), default=0)
    label_w = max(label_w, len("word"))
    col_w = [max(len(line) for line in column) for column in cells]
    width = 78
    out: list[str] = []
    start = 0
    headers = ["word", *[label for label, _ in rows]]
    while start < len(cells):
        used = label_w + 2
        end = start
        while end < len(cells) and used + col_w[end] + 1 <= width:
            used += col_w[end] + 1
            end += 1
        end = max(end, start + 1)
        for line_no, header in enumerate(headers):
            parts = [header.ljust(label_w)]
            parts += [cells[c][line_no].ljust(col_w[c]) for c in range(start, end)]
            out.append("  ".join(parts).rstrip())
        out.append("")
        start = end
    return _fence("\n".join(out).rstrip())


def _byte_to_char(text: str) -> dict[int, int]:
    """Return a map from UTF-8 byte offset to character offset in ``text``."""
    mapping: dict[int, int] = {}
    byte = 0
    for char_index, char in enumerate(text):
        mapping[byte] = char_index
        byte += len(char.encode("utf-8"))
    mapping[byte] = len(text)
    return mapping


def _byte_to_char_at(byte_char: Mapping[int, int], offset: int, length: int) -> int:
    """Map a byte offset to a character offset, snapping off-boundary offsets.

    When ``offset`` lands on a UTF-8 character boundary the mapped character
    offset is exact. When it falls inside a multi-byte codepoint (a malformed
    anchor) it snaps to the boundary of the codepoint that contains it rather
    than collapsing to ``0`` or ``length``, so a bad byte offset shifts the span
    by at most one character instead of stretching it across the whole text.
    """
    direct = byte_char.get(offset)
    if direct is not None:
        return direct
    clamped = max(0, min(offset, max(byte_char, default=0)))
    candidates = [b for b in byte_char if b <= clamped]
    if not candidates:
        return 0
    nearest = byte_char[max(candidates)]
    return min(nearest, length)


def span_overlay(text: str, spans: list[tuple[int, int, str]]) -> str:
    """Render labeled character spans as brat-style underlines over the text.

    ``spans`` is ``(charStart, charEnd, label)``; overlapping spans stack onto
    separate lanes so nesting stays legible.
    """
    if not text:
        return _fence("(no text)")
    clipped = [(max(0, s), min(len(text), e), label) for s, e, label in spans if s < e]
    lanes = _pack_lanes([(s, e) for s, e, _ in clipped])
    depth = (max(lanes) + 1) if lanes else 0
    grid = [[" "] * len(text) for _ in range(depth)]
    labels: list[list[tuple[int, str]]] = [[] for _ in range(depth)]
    for (start, end, label), lane in zip(clipped, lanes, strict=True):
        for col in range(start, end):
            grid[lane][col] = "▔"
        if label:
            labels[lane].append((start, label))
    out = [text]
    for lane in range(depth):
        out.append("".join(grid[lane]).rstrip())
        line = [" "] * len(text)
        for start, label in sorted(labels[lane]):
            for offset, char in enumerate(label):
                if start + offset < len(line):
                    line[start + offset] = char
        rendered = "".join(line).rstrip()
        if rendered:
            out.append(rendered)
    return _fence("\n".join(out))


def span_layer_overlay(
    browser: RepoBrowser, expr_uri: str, layer: Mapping[str, JsonValue]
) -> str:
    """Render a span-kind layer as labeled underlines over the expression text.

    Token-anchored spans resolve to character ranges through the tokenization;
    byte-anchored spans convert directly. Dataset-agnostic over the anchor union.
    """
    text = _str(_obj(browser.load_raw(expr_uri)).get("text"))
    if not text:
        return _fence("(no text)")
    tokens = {
        tok.index: tok
        for tok in tokenizations_of(browser, expr_uri).get(
            _layer_tokenization(layer), []
        )
    }
    byte_char = _byte_to_char(text)
    spans: list[tuple[int, int, str]] = []
    for raw in _items(layer.get("annotations")):
        ann = _obj(raw)
        label = _str(ann.get("label")) or _str(ann.get("value"))
        indexes = [i for i in anchor_token_indexes(ann.get("anchor")) if i in tokens]
        if indexes:
            byte_start = min(tokens[i].byte_start for i in indexes)
            byte_end = max(tokens[i].byte_end for i in indexes)
        else:
            byte_span = anchor_byte_span(ann.get("anchor"))
            if byte_span is None:
                continue
            byte_start, byte_end = byte_span
        start = _byte_to_char_at(byte_char, byte_start, len(text))
        end = _byte_to_char_at(byte_char, byte_end, len(text))
        spans.append((start, end, label))
    return span_overlay(text, spans)


def tier_timeline(
    tiers: list[tuple[str, list[tuple[int, int, str]]]], *, ms_per_col: int = 200
) -> str:
    """Render time-aligned tiers as an ELAN-style partitur grid.

    ``tiers`` is ``(tier_name, [(startMs, endMs, label)])``; a shared time ruler
    sits on top and each tier is a lane whose boundaries align by column.
    """
    spans = [span for _, items in tiers for span in items]
    if not spans:
        return _fence("(no time-aligned annotations)")
    end_ms = max(end for _, end, _ in spans)
    cols = max(1, end_ms // ms_per_col + 1)
    name_w = max((len(name) for name, _ in tiers), default=0)
    ruler = "".join(
        (f"{c * ms_per_col / 1000:.1f}".ljust(5) if c % 5 == 0 else "")
        for c in range(0, cols, 1)
    )
    out = [f"{'':<{name_w}}  {ruler}".rstrip()]
    for name, items in tiers:
        lane = [" "] * cols
        for start, end, label in items:
            a = start // ms_per_col
            b = max(a + 1, end // ms_per_col)
            lane[a] = "▏"
            for col in range(a + 1, min(b, cols)):
                lane[col] = "─"
            for offset, char in enumerate(label):
                if a + 1 + offset < min(b, cols):
                    lane[a + 1 + offset] = char
        out.append(f"{name:<{name_w}}  {''.join(lane)}".rstrip())
    return _fence("\n".join(out))


def document_tags(anns: list[Mapping[str, JsonValue]]) -> str:
    """Render document-level annotations as labeled chips.

    Confidence is the lexicon's integer score scaled 0-1000 (1000 = maximum) and
    is shown as a percentage of that range.
    """
    chips: list[str] = []
    for ann in anns:
        label = _str(ann.get("label")) or _str(ann.get("value"))
        confidence = ann.get("confidence")
        # confidence is an int scaled 0..1000 per the lexicon; 1000 == 100%.
        if isinstance(confidence, int):
            label += f" {confidence / 1000:.0%}"
        if label:
            chips.append(f"[ {label} ]")
    return _fence("  ".join(chips) if chips else "(no document tags)")


def graph_edges(
    nodes: Mapping[str, Mapping[str, JsonValue]],
    edges: list[Mapping[str, JsonValue]],
) -> str:
    """Render graph edges as a ``source --type--> target`` adjacency list.

    Node references resolve to a readable label through ``nodes`` (keyed by
    AT-URI) when present, else fall back to the ref's most specific id.
    """

    def name(ref: JsonValue) -> str:
        body = _obj(ref)
        record_ref = _str(body.get("recordRef"))
        node = nodes.get(record_ref)
        if node is not None:
            return _str(node.get("label") or node.get("name")) or _short_uri(record_ref)
        if record_ref:
            return _short_uri(record_ref)
        return _str(_uuid(body.get("localId")) or body.get("objectId"))

    out: list[str] = []
    for edge in edges[:400]:
        edge_type = _str(edge.get("edgeType")) or "related-to"
        label = _str(edge.get("label"))
        relation = f"{edge_type}/{label}" if label else edge_type
        out.append(
            f"{name(edge.get('source'))}  --{relation}-->  {name(edge.get('target'))}"
        )
    return _fence("\n".join(out) if out else "(no edges)")


def alignment_bitext(browser: RepoBrowser, data: Mapping[str, JsonValue]) -> str:
    """Render an alignment as source-to-target index links with surfaces."""

    def units(ref: JsonValue) -> dict[int, str]:
        body = _obj(ref)
        local = _uuid(body.get("localId"))
        record_ref = _str(body.get("recordRef"))
        for tok_id, tokens in _alignment_tokenizations(browser, data).items():
            if tok_id in (local, record_ref):
                return {tok.index: tok.text for tok in tokens}
        return {}

    source = units(data.get("source"))
    target = units(data.get("target"))
    out: list[str] = []
    for raw in _items(data.get("links"))[:400]:
        link = _obj(raw)
        src = [
            f"{i}:{source.get(i, '?')}"
            for i in _items(link.get("sourceIndices"))
            if isinstance(i, int)
        ]
        tgt = [
            f"{i}:{target.get(i, '?')}"
            for i in _items(link.get("targetIndices"))
            if isinstance(i, int)
        ]
        label = _str(link.get("label")) or "aligns"
        out.append(f"{' '.join(src) or '∅':<24} --{label}--> {' '.join(tgt) or '∅'}")
    return _fence("\n".join(out) if out else "(no links)")


def _alignment_tokenizations(
    browser: RepoBrowser, data: Mapping[str, JsonValue]
) -> dict[str, list[Token]]:
    """Return tokenizations reachable from an alignment's expression."""
    expr_uri = _str(data.get("expression"))
    if expr_uri:
        return tokenizations_of(browser, expr_uri)
    return {}


# ---- judgments (dispatch on taskType) --------------------------------------


def _response_values(
    judgments: list[Mapping[str, JsonValue]],
) -> tuple[list[int], list[str], list[str]]:
    """Split judgments into scalar, categorical, and free-text response lists."""
    scalars: list[int] = []
    categoricals: list[str] = []
    free: list[str] = []
    for judgment in judgments:
        scalar = judgment.get("scalarValue")
        if isinstance(scalar, int):
            scalars.append(scalar)
        categorical = _str(judgment.get("categoricalValue"))
        if categorical:
            categoricals.append(categorical)
        text = _str(judgment.get("freeText"))
        if text:
            free.append(text)
    return scalars, categoricals, free


def judgment_distribution(  # noqa: PLR0911 - one branch per taskType family
    experiment: Mapping[str, JsonValue],
    judgments: list[Mapping[str, JsonValue]],
) -> str:
    """Render a per-item judgment distribution dispatched on ``taskType``."""
    task = _str(experiment.get("taskType"))
    scalars, categoricals, free = _response_values(judgments)
    measure = _str(experiment.get("measureType")) or "judgment"
    header = f"{measure} · {task or 'task'} · n={len(judgments)}"
    if task == "ordinal-scale" and scalars:
        return f"{header}\n{_ordinal(experiment, scalars)}"
    if task == "magnitude" and scalars:
        return f"{header}\n{_magnitude(scalars)}"
    if task in ("forced-choice", "binary", "categorical", "multi-select", "preference"):
        return f"{header}\n{_categorical(categoricals)}"
    if task in ("free-text", "cloze") or (free and not scalars and not categoricals):
        return f"{header}\n{_free_text(free)}"
    if scalars:
        return f"{header}\n{_ordinal(experiment, scalars)}"
    if categoricals:
        return f"{header}\n{_categorical(categoricals)}"
    if free:
        return f"{header}\n{_free_text(free)}"
    return f"{header}\n*No responses.*"


def _ordinal(experiment: Mapping[str, JsonValue], scalars: list[int]) -> str:
    """Render an ordinal (Likert) distribution as a per-level histogram.

    The histogram spans the declared ``scaleMin``/``scaleMax`` when present, but
    is widened to include any responses that fall outside the declared scale so
    every counted scalar appears in a bar. The summary mean, median, and ``n``
    are then consistent with the bars and sparkline.
    """
    low = experiment.get("scaleMin")
    high = experiment.get("scaleMax")
    lo = min(low, *scalars) if isinstance(low, int) else min(scalars)
    hi = max(high, *scalars) if isinstance(high, int) else max(scalars)
    counts = {level: scalars.count(level) for level in range(lo, hi + 1)}
    peak = max(counts.values(), default=0)
    rows = [
        f"{level:>3}  {hbar(count, peak):<24} {count}"
        for level, count in counts.items()
    ]
    ordered = [counts[level] for level in range(lo, hi + 1)]
    mean = sum(scalars) / len(scalars)
    median = _median(scalars)
    summary = (
        f"{sparkline(ordered)}  mean {mean:.1f}  median {median:g}  n {len(scalars)}"
    )
    return _fence("\n".join([*rows, "", summary]))


def _median(scalars: list[int]) -> float:
    """Return the median of a non-empty list, averaging the two middle values.

    For an even-length list the median is the mean of the two central order
    statistics rather than the upper of the two.
    """
    ordered = sorted(scalars)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def _magnitude(scalars: list[int]) -> str:
    """Render a magnitude-estimation distribution with a geometric mean."""
    positive = [v for v in scalars if v > 0]
    if positive:
        geo = math.exp(sum(math.log(v) for v in positive) / len(positive))
        center = f"geo-mean {geo:.0f}"
    else:
        center = f"mean {sum(scalars) / len(scalars):.0f}"
    lo, hi = min(scalars), max(scalars)
    span = (hi - lo) or 1
    bins = [0] * 16
    for value in scalars:
        bins[min(15, int((value - lo) / span * 15))] += 1
    median = sorted(scalars)[len(scalars) // 2]
    line = f"{lo} {sparkline(bins)} {hi}"
    summary = f"{center}  median {median}  range {lo}..{hi}  n {len(scalars)}"
    return _fence(f"{line}\n{summary}")


def _categorical(categoricals: list[str]) -> str:
    """Render a categorical/forced-choice distribution as proportion bars."""
    counts: dict[str, int] = {}
    for value in categoricals:
        counts[value] = counts.get(value, 0) + 1
    total = len(categoricals) or 1
    peak = max(counts.values(), default=0)
    rows = [
        f"{label:<16} {hbar(count, peak):<24} {_pct(count, total)} ({count})"
        for label, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return _fence("\n".join(rows) if rows else "(no responses)")


def _free_text(free: list[str]) -> str:
    """Render free-text responses as a frequency-ranked list."""
    counts: dict[str, int] = {}
    for value in free:
        counts[value] = counts.get(value, 0) + 1
    rows = [
        f"{count:>3}  {_truncate(value, 64)}"
        for value, count in sorted(counts.items(), key=lambda kv: -kv[1])[:40]
    ]
    return _fence("\n".join(rows) if rows else "(no responses)")
