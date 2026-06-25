"""Type-aware rendering of Layers records for the Browse tab.

:func:`render_record` dispatches on a record's collection NSID to a Markdown view
that fits the data: an ontology renders as a type hierarchy, an experiment as a
design plus its response sets, a graph as relation cards, a lexicon collection as
its entries, an annotation layer as annotations over text, and so on. Records
without a bespoke view fall back to a clean key-value rendering, so every record
type is viewable.

Everything reads the record's raw JSON (``JsonValue``) rather than typed
attributes, so the helpers stay concretely typed. :data:`LIST_COLUMNS` and
:func:`summarize` drive the records list with type-appropriate columns.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from lairs.tui import viz

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from lairs._types import JsonValue
    from lairs.tui.browse import RepoBrowser

__all__ = [
    "columns_for",
    "record_views",
    "render_record",
    "render_view",
    "summarize",
    "view_modes",
]

_MAX_RELATED = 200
_TEXT_PREVIEW = 600

_TYPEDEF_NSID = "pub.layers.ontology.typeDef"
_JUDGMENT_SET_NSID = "pub.layers.judgment.judgmentSet"
_AGREEMENT_NSID = "pub.layers.judgment.agreementReport"
_COLLECTION_MEMBERSHIP_NSID = "pub.layers.resource.collectionMembership"
_CORPUS_MEMBERSHIP_NSID = "pub.layers.corpus.membership"
_EXPRESSION_NSID = "pub.layers.expression.expression"
_LAYER_NSID = "pub.layers.annotation.annotationLayer"


# ---- small accessors over raw JSON ----------------------------------------


def _obj(value: JsonValue) -> Mapping[str, JsonValue]:
    """Return a value as a mapping, or an empty mapping when it is not one."""
    return value if isinstance(value, dict) else {}


def _items(value: JsonValue) -> list[JsonValue]:
    """Return a value as a list, or an empty list when it is not one."""
    return value if isinstance(value, list) else []


def _str(value: JsonValue) -> str:
    """Render a JSON value to a compact display string."""
    return "" if value is None else str(value)


def _short_uri(value: JsonValue) -> str:
    """Shorten an AT-URI to ``<collection-tail>/<rkey>`` for display."""
    text = _str(value)
    if not text.startswith("at://"):
        return text
    parts = text.split("/")
    min_parts = 2
    return "/".join(parts[-2:]) if len(parts) >= min_parts else text


def _truncate(text: str, limit: int) -> str:
    """Truncate text to a limit with an ellipsis."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _license(licensing: JsonValue) -> str:
    """Render a licensing object to its expression or first SPDX id."""
    body = _obj(licensing)
    if body.get("expression"):
        return _str(body.get("expression"))
    licenses = _items(body.get("licenses"))
    return _str(_obj(licenses[0]).get("spdx")) if licenses else ""


def _knowledge_ref(ref: JsonValue) -> str:
    """Render a knowledge reference as ``source:identifier`` (+ label)."""
    body = _obj(ref)
    source = _str(body.get("source"))
    identifier = _str(body.get("identifier"))
    head = f"{source}:{identifier}" if source else identifier
    label = body.get("label")
    return f"{head} ({_str(label)})" if label else head


def _object_ref(ref: JsonValue) -> str:
    """Render an objectRef to its most specific populated target."""
    body = _obj(ref)
    if body.get("recordRef"):
        return _short_uri(body.get("recordRef"))
    if body.get("knowledgeRef"):
        return _knowledge_ref(body.get("knowledgeRef"))
    return _str(body.get("localId") or body.get("objectId"))


def _refs(values: JsonValue) -> str:
    """Render an array of AT-URI refs to a short comma-joined string."""
    return ", ".join(_short_uri(ref) for ref in _items(values))


def _kv(rows: list[tuple[str, str]]) -> list[str]:
    """Render non-empty ``(label, value)`` rows as a Markdown table."""
    kept = [(label, value) for label, value in rows if value]
    if not kept:
        return []
    return ["| field | value |", "| --- | --- |", *(f"| {a} | {b} |" for a, b in kept)]


def _provenance(data: Mapping[str, JsonValue]) -> list[tuple[str, str]]:
    """Build the licensing/eprint/knowledge rows shared by produce records."""
    knowledge = _items(data.get("knowledgeRefs"))
    return [
        ("licensing", _license(data.get("licensing"))),
        ("eprints", _refs(data.get("eprintRefs"))),
        ("knowledge", ", ".join(_knowledge_ref(r) for r in knowledge)),
        ("created", _str(data.get("createdAt"))),
    ]


def _footer(uri: str) -> list[str]:
    """Return the trailing AT-URI footer lines."""
    return ["", f"`{uri}`"]


# ---- bespoke renderers ----------------------------------------------------


def _render_ontology(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render an ontology as a header plus its type hierarchy."""
    lines = [f"# {_str(data.get('name'))}", ""]
    if data.get("description"):
        lines += [_str(data.get("description")), ""]
    lines += _kv(
        [
            ("domain", _str(data.get("domain"))),
            ("version", _str(data.get("version"))),
            ("parent", _short_uri(data.get("parentRef"))),
            ("persona", _short_uri(data.get("personaRef"))),
            *_provenance(data),
        ]
    )
    type_defs = browser.related_raw(_TYPEDEF_NSID, "ontologyRef", uri)
    lines += ["", f"## Type hierarchy ({len(type_defs)})", ""]
    if not type_defs:
        lines.append("*No type definitions in this repository.*")
    grouped: dict[str, list[Mapping[str, JsonValue]]] = {}
    for _, type_def in type_defs[:_MAX_RELATED]:
        grouped.setdefault(_str(type_def.get("typeKind")) or "other", []).append(
            type_def
        )
    for kind in sorted(grouped):
        lines += ["", f"### {kind} ({len(grouped[kind])})", ""]
        for type_def in grouped[kind]:
            gloss = _str(type_def.get("gloss"))
            parent = type_def.get("parentTypeRef")
            roles = _items(type_def.get("allowedRoles"))
            suffix = f" — {gloss}" if gloss else ""
            parent_note = f"  ↳ extends `{_short_uri(parent)}`" if parent else ""
            role_note = f"  ({len(roles)} roles)" if roles else ""
            lines.append(
                f"- **{_str(type_def.get('name'))}**{suffix}{parent_note}{role_note}"
            )
    return "\n".join(lines + _footer(uri))


def _render_experiment(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render an experiment definition as its design plus response sets."""
    lines = [f"# {_str(data.get('name'))}", ""]
    if data.get("description"):
        lines += [_str(data.get("description")), ""]
    scale_min, scale_max = data.get("scaleMin"), data.get("scaleMax")
    scale = f"{_str(scale_min)}..{_str(scale_max)}" if scale_min is not None else ""
    lines += ["## Design", ""]
    lines += _kv(
        [
            ("measure", _str(data.get("measureType"))),
            ("task", _str(data.get("taskType"))),
            ("scale", scale),
            ("labels", ", ".join(_str(v) for v in _items(data.get("labels")))),
        ]
    )
    materials = _kv(
        [
            ("corpus", _short_uri(data.get("corpusRef"))),
            ("ontology", _short_uri(data.get("ontologyRef"))),
            ("persona", _short_uri(data.get("personaRef"))),
            ("templates", _refs(data.get("templateRefs"))),
            ("collections", _refs(data.get("collectionRefs"))),
            *_provenance(data),
        ]
    )
    if materials:
        lines += ["", "## Materials", "", *materials]
    sets = browser.related_raw(_JUDGMENT_SET_NSID, "experimentRef", uri)
    reports = browser.related_raw(_AGREEMENT_NSID, "experimentRef", uri)
    lines += ["", f"## Responses ({len(sets)} judgment sets)", ""]
    for _, judgment_set in sets[:_MAX_RELATED]:
        count = len(_items(judgment_set.get("judgments")))
        agent = _obj(judgment_set.get("agent"))
        who = _str(agent.get("name") or agent.get("did"))
        lines.append(f"- {count} judgments{f' by {who}' if who else ''}")
    if reports:
        lines += ["", f"## Agreement ({len(reports)})", ""]
        for _, report in reports[:_MAX_RELATED]:
            lines.append(
                f"- {_str(report.get('metric'))} = {_str(report.get('value'))} "
                f"({_str(report.get('numAnnotators'))} annotators)"
            )
    return "\n".join(lines + _footer(uri))


def _render_judgment_set(
    _browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render a judgment set: its experiment, agent, and response summary."""
    judgments = _items(data.get("judgments"))
    agent = _obj(data.get("agent"))
    lines = ["# Judgment set", ""]
    lines += _kv(
        [
            ("experiment", _short_uri(data.get("experimentRef"))),
            ("agent", _str(agent.get("name") or agent.get("did") or agent.get("id"))),
            ("judgments", _str(len(judgments))),
            ("created", _str(data.get("createdAt"))),
        ]
    )
    counts: dict[str, int] = {}
    for judgment in judgments:
        value = _obj(judgment).get("categoricalValue")
        if value:
            counts[_str(value)] = counts.get(_str(value), 0) + 1
    if counts:
        lines += ["", "## Response distribution", ""]
        lines += [
            f"- `{v}`: {counts[v]}" for v in sorted(counts, key=lambda k: -counts[k])
        ]
    return "\n".join(lines + _footer(uri))


def _render_graph_edge_set(
    _browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render an edge set as relation cards (source -> type -> target)."""
    edges = _items(data.get("edges"))
    default_type = _str(data.get("edgeType"))
    lines = [f"# Edge set ({default_type or 'graph'})", "", f"{len(edges)} edges", ""]
    for raw_edge in edges[:_MAX_RELATED]:
        edge = _obj(raw_edge)
        source = _object_ref(edge.get("source"))
        target = _object_ref(edge.get("target"))
        edge_type = _str(edge.get("edgeType")) or default_type or "related-to"
        lines.append(f"- `{source}` → **{edge_type}** → `{target}`")
    if len(edges) > _MAX_RELATED:
        lines.append(f"- *… {len(edges) - _MAX_RELATED} more*")
    return "\n".join(lines + _footer(uri))


def _render_collection(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render a resource collection as its entries."""
    lines = [f"# {_str(data.get('name'))}", ""]
    if data.get("description"):
        lines += [_str(data.get("description")), ""]
    lines += _kv(
        [
            ("kind", _str(data.get("kind"))),
            ("version", _str(data.get("version"))),
            ("ontology", _short_uri(data.get("ontologyRef"))),
            *_provenance(data),
        ]
    )
    members = browser.related_raw(_COLLECTION_MEMBERSHIP_NSID, "collectionRef", uri)
    lines += ["", f"## Entries ({len(members)})", ""]
    if members:
        lines += ["| form | components |", "| --- | --- |"]
    for _, membership in members[:_MAX_RELATED]:
        entry = _obj(browser.load_raw(_str(membership.get("entryRef"))))
        if not entry:
            continue
        components = " ".join(
            _str(_obj(c).get("form")) for c in _items(entry.get("components"))
        )
        lines.append(f"| {_str(entry.get('form'))} | {components} |")
    return "\n".join(lines + _footer(uri))


def _render_annotation_layer(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render an annotation layer as its annotations over the source text."""
    annotations = _items(data.get("annotations"))
    subkind = data.get("subkind")
    head = f"{_str(data.get('kind'))}{'/' + _str(subkind) if subkind else ''}"
    lines = [f"# Annotation layer ({head})", ""]
    lines += _kv(
        [
            ("expression", _short_uri(data.get("expression"))),
            ("formalism", _str(data.get("formalism"))),
            ("label set", _str(data.get("labelSet"))),
            ("source method", _str(data.get("sourceMethod"))),
            ("annotations", _str(len(annotations))),
        ]
    )
    source = _obj(browser.load_raw(_str(data.get("expression"))))
    text = _str(source.get("text"))
    lines += ["", "## Annotations", ""]
    if annotations:
        lines += ["| label | span |", "| --- | --- |"]
    for raw_ann in annotations[:_MAX_RELATED]:
        ann = _obj(raw_ann)
        span = _span_text(ann.get("anchor"), text)
        lines.append(f"| {_str(ann.get('label')) or '-'} | {span} |")
    return "\n".join(lines + _footer(uri))


def _span_text(anchor: JsonValue, text: str) -> str:
    """Return the source text under an anchor, or a token-anchor summary.

    A byte span slices the source text; a token reference renders as its token
    index (or index range for a sequence), so token-anchored annotations, the
    common case for treebank conversions, still read meaningfully.
    """
    body = _obj(anchor)
    span = _obj(body.get("textSpan")) or body
    start, end = span.get("byteStart"), span.get("byteEnd")
    if isinstance(start, int) and isinstance(end, int) and text:
        raw = text.encode("utf-8")[start:end].decode("utf-8", "replace")
        return _truncate(raw.replace("\n", " "), 80)
    token_ref = _obj(body.get("tokenRef"))
    if token_ref.get("tokenIndex") is not None:
        return f"token {_str(token_ref.get('tokenIndex'))}"
    indexes = [
        i
        for i in _items(_obj(body.get("tokenRefSequence")).get("tokenIndexes"))
        if isinstance(i, int)
    ]
    if indexes:
        low, high = min(indexes), max(indexes)
        return f"token {low}" if low == high else f"tokens {low}..{high}"
    token_index = body.get("tokenIndex")
    return f"token {_str(token_index)}" if token_index is not None else ""


def _render_corpus(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render a corpus as its metadata plus membership list."""
    lines = [f"# {_str(data.get('name'))}", ""]
    if data.get("description"):
        lines += [_str(data.get("description")), ""]
    lines += _kv(
        [
            ("domain", _str(data.get("domain"))),
            ("version", _str(data.get("version"))),
            ("languages", ", ".join(_str(v) for v in _items(data.get("languages")))),
            ("expressions", _str(data.get("expressionCount"))),
            ("ontologies", _refs(data.get("ontologyRefs"))),
            *_provenance(data),
        ]
    )
    members = browser.related_raw(_CORPUS_MEMBERSHIP_NSID, "corpusRef", uri)
    lines += ["", f"## Members ({len(members)})", ""]
    for _, membership in members[:_MAX_RELATED]:
        split = membership.get("split")
        split_note = f" [{_str(split)}]" if split else ""
        lines.append(f"- `{_short_uri(membership.get('expressionRef'))}`{split_note}")
    return "\n".join(lines + _footer(uri))


def _render_expression(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render an expression as its text, sub-expressions, and layers."""
    lines = [f"# {_str(data.get('id'))} ({_str(data.get('kind'))})", ""]
    lines += _kv(
        [
            ("languages", ", ".join(_str(v) for v in _items(data.get("languages")))),
            ("parent", _short_uri(data.get("parentRef"))),
            ("media", _short_uri(data.get("mediaRef"))),
        ]
    )
    if data.get("text"):
        lines += [
            "",
            "## Text",
            "",
            "> " + _truncate(_str(data.get("text")), _TEXT_PREVIEW),
        ]
    children = browser.related_raw(_EXPRESSION_NSID, "parentRef", uri)
    if children:
        lines += ["", f"## Sub-expressions ({len(children)})", ""]
        lines += [
            f"- {_str(c.get('id'))} ({_str(c.get('kind'))})"
            for _, c in children[:_MAX_RELATED]
        ]
    layers = browser.related_raw(_LAYER_NSID, "expression", uri)
    if layers:
        lines += ["", f"## Annotation layers ({len(layers)})", ""]
        for _, layer in layers[:_MAX_RELATED]:
            sub = layer.get("subkind")
            lines.append(f"- {_str(layer.get('kind'))}{'/' + _str(sub) if sub else ''}")
    return "\n".join(lines + _footer(uri))


def _render_media(
    _browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render a media record as its technical metadata."""
    lines = [f"# {_str(data.get('title')) or _str(data.get('kind'))}", ""]
    lines += _kv(
        [
            ("kind", _str(data.get("kind"))),
            ("mime", _str(data.get("mimeType"))),
            ("duration ms", _str(data.get("durationMs"))),
            ("external", _str(data.get("externalUri"))),
            ("licensing", _license(data.get("licensing"))),
        ]
    )
    return "\n".join(lines + _footer(uri))


def _render_persona(
    _browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render a persona as its framework and guidelines."""
    lines = [f"# {_str(data.get('name'))}", ""]
    if data.get("description"):
        lines += [_str(data.get("description")), ""]
    lines += _kv(
        [
            ("domain", _str(data.get("domain"))),
            ("kind", _str(data.get("kind"))),
            ("ontologies", _refs(data.get("ontologyRefs"))),
            ("licensing", _license(data.get("licensing"))),
        ]
    )
    if data.get("guidelines"):
        lines += [
            "",
            "## Guidelines",
            "",
            _truncate(_str(data.get("guidelines")), _TEXT_PREVIEW),
        ]
    return "\n".join(lines + _footer(uri))


def _render_eprint(
    _browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render an eprint as its citation and links."""
    citation = _obj(data.get("citation"))
    title = citation.get("title") or citation.get("raw")
    lines = [f"# {_str(title) or _str(data.get('eprintIdentifier'))}", ""]
    names = [
        _str(_obj(c).get("literal") or _obj(c).get("family") or _obj(c).get("given"))
        for c in _items(citation.get("creators"))
    ]
    lines += _kv(
        [
            ("identifier", _str(data.get("eprintIdentifier"))),
            ("id type", _str(data.get("eprintIdentifierType"))),
            ("link type", _str(data.get("linkType"))),
            ("creators", ", ".join(n for n in names if n)),
            ("doi", _str(citation.get("doi"))),
            ("venue", _str(citation.get("containerTitle"))),
        ]
    )
    return "\n".join(lines + _footer(uri))


# ---- generic fallback -----------------------------------------------------


def _render_generic(uri: str, data: Mapping[str, JsonValue]) -> str:
    """Render any record as a clean nested key-value view."""
    lines = [f"# {_short_uri(uri)}", ""]
    scalars: list[tuple[str, str]] = []
    nested: list[tuple[str, JsonValue]] = []
    for key, value in data.items():
        if value in (None, "", []):
            continue
        if isinstance(value, (dict, list)):
            nested.append((key, value))
        else:
            scalars.append((key, _str(value)))
    lines += _kv(scalars)
    for key, value in nested:
        if isinstance(value, list):
            lines += ["", f"## {key} ({len(value)})", ""]
            lines += [
                f"- `{_truncate(json.dumps(item, default=str), 200)}`"
                for item in value[:_MAX_RELATED]
            ]
        else:
            lines += [
                "",
                f"## {key}",
                "",
                f"`{_truncate(json.dumps(value, default=str), 400)}`",
            ]
    return "\n".join(lines + _footer(uri))


_RENDERERS = {
    "pub.layers.ontology.ontology": _render_ontology,
    "pub.layers.judgment.experimentDef": _render_experiment,
    "pub.layers.judgment.judgmentSet": _render_judgment_set,
    "pub.layers.graph.graphEdgeSet": _render_graph_edge_set,
    "pub.layers.resource.collection": _render_collection,
    "pub.layers.annotation.annotationLayer": _render_annotation_layer,
    "pub.layers.corpus.corpus": _render_corpus,
    "pub.layers.expression.expression": _render_expression,
    "pub.layers.media.media": _render_media,
    "pub.layers.persona.persona": _render_persona,
    "pub.layers.eprint.eprint": _render_eprint,
}


_SEGMENTATION_NSID = "pub.layers.segmentation.segmentation"
_ALIGNMENT_NSID = "pub.layers.alignment.alignment"
_GRAPH_EDGE_SET_NSID = "pub.layers.graph.graphEdgeSet"
_GRAPH_EDGE_NSID = "pub.layers.graph.graphEdge"
_GRAPH_NODE_NSID = "pub.layers.graph.graphNode"

# id(browser) -> {item AT-URI: (experimentRef, [judgment dicts])}, built once.
_ITEM_INDEX: dict[int, dict[str, tuple[str, list[Mapping[str, JsonValue]]]]] = {}


# ---- view producers (one focused, uncluttered view per mode) ---------------


def _descendant_texts(browser: RepoBrowser, uri: str) -> list[str]:
    """Return the texts of an expression's descendant leaves, in order."""
    own = _str(_obj(browser.load_raw(uri)).get("text"))
    if own:
        return [own]
    children = browser.related_raw(_EXPRESSION_NSID, "parentRef", uri)
    texts: list[str] = []
    for child_uri, _ in children:
        texts += _descendant_texts(browser, child_uri)
    return texts


def _expression_text(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> str:
    """Render an expression's readable text, assembling documents from leaves."""
    text = _str(data.get("text"))
    body = text or "\n\n".join(_descendant_texts(browser, uri))
    return body or "*(no text)*"


def _layers_roster(browser: RepoBrowser, uri: str) -> str:
    """List the annotation layers anchored to an expression."""
    rows = ["| kind | subkind | formalism | annotations |", "| --- | --- | --- | --- |"]
    for _, layer in viz.layers_of(browser, uri):
        rows.append(
            f"| {_str(layer.get('kind'))} | {_str(layer.get('subkind')) or '-'} "
            f"| {_str(layer.get('formalism')) or '-'} "
            f"| {len(_items(layer.get('annotations')))} |"
        )
    return "\n".join(rows) if len(rows) > 2 else "*No annotation layers.*"  # noqa: PLR2004


def _item_index(
    browser: RepoBrowser,
) -> dict[str, tuple[str, list[Mapping[str, JsonValue]]]]:
    """Build (and cache) the map from a judged item AT-URI to its judgments."""
    key = id(browser)
    if key not in _ITEM_INDEX:
        index: dict[str, tuple[str, list[Mapping[str, JsonValue]]]] = {}
        for _, jset in browser.records_raw(_JUDGMENT_SET_NSID):
            experiment = _str(jset.get("experimentRef"))
            for raw in _items(jset.get("judgments")):
                judgment = _obj(raw)
                item = _str(_obj(judgment.get("item")).get("recordRef"))
                if item:
                    index.setdefault(item, (experiment, []))[1].append(judgment)
        _ITEM_INDEX[key] = index
    return _ITEM_INDEX[key]


def _graph_nodes(browser: RepoBrowser) -> dict[str, Mapping[str, JsonValue]]:
    """Return graph nodes keyed by AT-URI for edge-label resolution."""
    return dict(browser.records_raw(_GRAPH_NODE_NSID))


def _expression_graph_edges(
    browser: RepoBrowser, uri: str
) -> list[Mapping[str, JsonValue]]:
    """Return graph edges whose provenance ties them to an expression."""
    edges: list[Mapping[str, JsonValue]] = []
    for _, edge in browser.records_raw(_GRAPH_EDGE_NSID):
        if viz.feature_map(edge.get("properties")).get("uds_expression") == uri:
            edges.append(edge)
    return edges


def _item_judgment_view(
    browser: RepoBrowser,
    item_text: str,
    bundle: tuple[str, list[Mapping[str, JsonValue]]],
) -> str:
    """Render the aggregated judgment distribution for a judged item."""
    experiment_uri, judgments = bundle
    experiment = _obj(browser.load_raw(experiment_uri))
    header = f"> {_truncate(item_text, 200)}\n" if item_text else ""
    return header + viz.judgment_distribution(experiment, judgments)


def _judgmentset_view(browser: RepoBrowser, data: Mapping[str, JsonValue]) -> str:
    """Render one annotator's judgment set as item-to-response rows."""
    agent = _obj(data.get("agent"))
    who = _str(agent.get("name") or agent.get("did") or agent.get("id"))
    rows = [f"agent: {who}" if who else "agent: (anonymous)", ""]
    table = ["| item | response |", "| --- | --- |"]
    for raw in _items(data.get("judgments"))[:_MAX_RELATED]:
        judgment = _obj(raw)
        item_uri = _str(_obj(judgment.get("item")).get("recordRef"))
        item_text = _truncate(_str(_obj(browser.load_raw(item_uri)).get("text")), 64)
        response = _str(judgment.get("scalarValue"))
        if not response:
            response = _str(
                judgment.get("categoricalValue") or judgment.get("freeText")
            )
        table.append(f"| {item_text or _short_uri(item_uri)} | {response} |")
    return "\n".join(rows + table)


def _graph_record_view(
    browser: RepoBrowser, nsid: str, data: Mapping[str, JsonValue]
) -> str:
    """Render a graph edge set or single edge as resolved adjacency."""
    nodes = _graph_nodes(browser)
    if nsid == _GRAPH_EDGE_SET_NSID:
        edges = [_obj(entry) for entry in _items(data.get("edges"))]
    else:
        edges = [data]
    return viz.graph_edges(nodes, edges)


def _span_layers_view(
    browser: RepoBrowser, uri: str, layers: list[Mapping[str, JsonValue]]
) -> str:
    """Render every span layer over an expression as stacked overlays."""
    return "\n\n".join(viz.span_layer_overlay(browser, uri, layer) for layer in layers)


def _thunks(
    pairs: list[tuple[str, Callable[[], str]]],
) -> list[tuple[str, Callable[[], str]]]:
    """Pass through the ordered ``(label, render)`` view list."""
    return pairs


def _expression_views(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> list[tuple[str, Callable[[], str]]]:
    """Return the focused views available for an expression record."""
    views: list[tuple[str, Callable[[], str]]] = [
        ("Text", lambda: _expression_text(browser, uri, data))
    ]
    syntax = viz.assemble_syntax(browser, uri)
    if syntax is not None and (syntax.tags or syntax.deps):
        views.append(("Grid", lambda: viz.conllu_grid(syntax)))
    if syntax is not None and syntax.deps:
        views.append(("Tree", lambda: viz.dependency_tree(syntax)))
    span_layers = [
        layer
        for _, layer in viz.layers_of(browser, uri)
        if _str(layer.get("kind")) == "span"
    ]
    if span_layers:
        views.append(("Spans", lambda: _span_layers_view(browser, uri, span_layers)))
    edges = _expression_graph_edges(browser, uri)
    if edges:
        nodes = _graph_nodes(browser)
        views.append(("Graph", lambda: viz.graph_edges(nodes, edges)))
    bundle = _item_index(browser).get(uri)
    if bundle is not None:
        views.append(
            (
                "Judgments",
                lambda: _item_judgment_view(browser, _str(data.get("text")), bundle),
            )
        )
    if viz.layers_of(browser, uri):
        views.append(("Layers", lambda: _layers_roster(browser, uri)))
    views.append(("Detail", lambda: _render_generic(uri, data)))
    return views


def _layer_views(
    browser: RepoBrowser, uri: str, data: Mapping[str, JsonValue]
) -> list[tuple[str, Callable[[], str]]]:
    """Return the focused views for an annotation layer, by kind."""
    kind = _str(data.get("kind"))
    subkind = _str(data.get("subkind"))
    expr = _str(data.get("expression"))
    views: list[tuple[str, Callable[[], str]]] = []
    if kind == "token-tag":
        views.append(("Tags", lambda: viz.token_tag_interlinear(browser, expr, data)))
    elif kind in ("relation", "tree") and subkind in (
        "dependency",
        "enhanced-dependency",
    ):
        syntax = viz.single_dep_syntax(browser, expr, data)
        if syntax is not None:
            views.append(("Tree", lambda: viz.dependency_tree(syntax)))
            views.append(("Grid", lambda: viz.conllu_grid(syntax)))
    elif kind == "span":
        views.append(("Spans", lambda: viz.span_layer_overlay(browser, expr, data)))
    elif kind == "graph":
        nodes = _graph_nodes(browser)
        anns = [_obj(a) for a in _items(data.get("annotations"))]
        views.append(("Graph", lambda: viz.graph_edges(nodes, anns)))
    elif kind == "tier":
        views.append(("Timeline", lambda: _tier_layer_view(data)))
    elif kind == "document-tag":
        anns = [_obj(a) for a in _items(data.get("annotations"))]
        views.append(("Tags", lambda: viz.document_tags(anns)))
    views.append(("Detail", lambda: _render_annotation_layer(browser, uri, data)))
    return views


def _tier_layer_view(data: Mapping[str, JsonValue]) -> str:
    """Render a tier layer's temporally-anchored annotations as one lane."""
    name = _str(data.get("subkind")) or _str(data.get("kind")) or "tier"
    spans: list[tuple[int, int, str]] = []
    for raw in _items(data.get("annotations")):
        ann = _obj(raw)
        time_span = viz.anchor_time_span(ann.get("anchor"))
        if time_span is not None:
            label = _str(ann.get("label")) or _str(ann.get("value"))
            spans.append((time_span[0], time_span[1], label))
    return viz.tier_timeline([(name, spans)])


def record_views(  # noqa: PLR0911 - one branch per record family
    browser: RepoBrowser,
    nsid: str,
    uri: str,
    data: Mapping[str, JsonValue],
) -> list[tuple[str, Callable[[], str]]]:
    """Return the ordered ``(label, render)`` views available for a record.

    Each view is a single focused visualization; the caller flips between them.
    Only views with content for this record are offered, so the panel stays
    uncluttered. A ``Detail`` view is always last so every field stays reachable.
    """
    if nsid == _EXPRESSION_NSID:
        return _expression_views(browser, uri, data)
    if nsid == _LAYER_NSID:
        return _layer_views(browser, uri, data)
    if nsid == _SEGMENTATION_NSID:
        return _thunks(
            [
                ("Tokens", lambda: viz.segmentation_tokens(browser, data)),
                ("Detail", lambda: _render_generic(uri, data)),
            ]
        )
    if nsid == _ALIGNMENT_NSID:
        return _thunks(
            [
                ("Bitext", lambda: viz.alignment_bitext(browser, data)),
                ("Detail", lambda: _render_generic(uri, data)),
            ]
        )
    if nsid in (_GRAPH_EDGE_SET_NSID, _GRAPH_EDGE_NSID):
        return _thunks(
            [
                ("Graph", lambda: _graph_record_view(browser, nsid, data)),
                ("Detail", lambda: _render_generic(uri, data)),
            ]
        )
    if nsid == _JUDGMENT_SET_NSID:
        return _thunks(
            [
                ("Responses", lambda: _judgmentset_view(browser, data)),
                ("Detail", lambda: _render_generic(uri, data)),
            ]
        )
    overview = _RENDERERS.get(nsid)
    views: list[tuple[str, Callable[[], str]]] = []
    if overview is not None:
        views.append(("Overview", lambda: overview(browser, uri, data)))
    views.append(("Detail", lambda: _render_generic(uri, data)))
    return views


def view_modes(
    browser: RepoBrowser, nsid: str, uri: str, data: Mapping[str, JsonValue]
) -> list[str]:
    """Return the labels of the views available for a record."""
    return [label for label, _ in record_views(browser, nsid, uri, data)]


def render_view(
    browser: RepoBrowser,
    nsid: str,
    uri: str,
    data: Mapping[str, JsonValue],
    mode: str,
) -> str:
    """Render one named view of a record, falling back to the first view."""
    views = record_views(browser, nsid, uri, data)
    for label, render in views:
        if label == mode:
            return render()
    return views[0][1]() if views else _render_generic(uri, data)


def render_record(
    browser: RepoBrowser,
    nsid: str,
    uri: str,
    data: Mapping[str, JsonValue],
) -> str:
    """Render a record's first (default) view."""
    views = record_views(browser, nsid, uri, data)
    return views[0][1]() if views else _render_generic(uri, data)


# ---- records-list columns -------------------------------------------------


def _count(value: JsonValue) -> str:
    """Render the length of a JSON array as a string."""
    return _str(len(_items(value)))


LIST_COLUMNS: dict[str, tuple[str, ...]] = {
    "pub.layers.corpus.corpus": ("Name", "Domain", "#Expr"),
    "pub.layers.expression.expression": ("Id", "Kind", "Text"),
    "pub.layers.annotation.annotationLayer": ("Kind", "Subkind", "Expression"),
    "pub.layers.ontology.ontology": ("Name", "Domain", "Version"),
    "pub.layers.ontology.typeDef": ("Name", "Type kind", "Ontology"),
    "pub.layers.resource.collection": ("Name", "Kind", "Version"),
    "pub.layers.resource.entry": ("Form", "#Components"),
    "pub.layers.judgment.experimentDef": ("Name", "Measure", "Task"),
    "pub.layers.judgment.judgmentSet": ("Experiment", "#Judgments"),
    "pub.layers.judgment.agreementReport": ("Metric", "Value", "#Annotators"),
    "pub.layers.graph.graphEdgeSet": ("Edge type", "#Edges"),
    "pub.layers.media.media": ("Kind", "Title"),
    "pub.layers.persona.persona": ("Name", "Domain", "Kind"),
    "pub.layers.eprint.eprint": ("Identifier", "Link type"),
}


def _summarize(nsid: str, data: Mapping[str, JsonValue]) -> tuple[str, ...] | None:
    """Return the type-appropriate summary cells, or ``None`` for the default."""
    g = data.get
    builders: dict[str, tuple[str, ...]] = {
        "pub.layers.corpus.corpus": (
            _str(g("name")),
            _str(g("domain")),
            _str(g("expressionCount")),
        ),
        "pub.layers.expression.expression": (
            _str(g("id")),
            _str(g("kind")),
            _truncate(_str(g("text")), 60),
        ),
        "pub.layers.annotation.annotationLayer": (
            _str(g("kind")),
            _str(g("subkind")),
            _short_uri(g("expression")),
        ),
        "pub.layers.ontology.ontology": (
            _str(g("name")),
            _str(g("domain")),
            _str(g("version")),
        ),
        "pub.layers.ontology.typeDef": (
            _str(g("name")),
            _str(g("typeKind")),
            _short_uri(g("ontologyRef")),
        ),
        "pub.layers.resource.collection": (
            _str(g("name")),
            _str(g("kind")),
            _str(g("version")),
        ),
        "pub.layers.resource.entry": (_str(g("form")), _count(g("components"))),
        "pub.layers.judgment.experimentDef": (
            _str(g("name")),
            _str(g("measureType")),
            _str(g("taskType")),
        ),
        "pub.layers.judgment.judgmentSet": (
            _short_uri(g("experimentRef")),
            _count(g("judgments")),
        ),
        "pub.layers.judgment.agreementReport": (
            _str(g("metric")),
            _str(g("value")),
            _str(g("numAnnotators")),
        ),
        "pub.layers.graph.graphEdgeSet": (_str(g("edgeType")), _count(g("edges"))),
        "pub.layers.media.media": (_str(g("kind")), _str(g("title"))),
        "pub.layers.persona.persona": (
            _str(g("name")),
            _str(g("domain")),
            _str(g("kind")),
        ),
        "pub.layers.eprint.eprint": (_str(g("eprintIdentifier")), _str(g("linkType"))),
    }
    return builders.get(nsid)


def columns_for(nsid: str) -> tuple[str, ...]:
    """Return the records-list columns for a record type, or a generic default."""
    return LIST_COLUMNS.get(nsid, ("Record",))


def summarize(nsid: str, uri: str, data: Mapping[str, JsonValue]) -> tuple[str, ...]:
    """Return a one-row summary of a record matching :func:`columns_for`.

    Parameters
    ----------
    nsid : str
        The record's collection NSID.
    uri : str
        The record's AT-URI, used by the generic summary.
    data : collections.abc.Mapping
        The record's raw JSON.

    Returns
    -------
    tuple of str
        The cell values for the record's row.
    """
    cells = _summarize(nsid, data)
    if cells is not None:
        return cells
    name = data.get("name") or data.get("id") or data.get("title")
    return (_str(name) or _short_uri(uri),)
