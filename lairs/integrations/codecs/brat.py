"""brat standoff format codec.

Converts between brat standoff annotation files and lairs records, binding to
the :class:`~lairs.integrations.ports.Codec` port. brat is a plain-text format,
so this codec parses it directly with no third-party dependency even when the
``lairs[brat]`` extra is declared.

The brat standoff format pairs a ``.txt`` document with a ``.ann`` annotation
file. The ``.ann`` lines this codec understands are:

- ``Tn<TAB>TYPE START END<TAB>TEXT`` - a text-bound entity, where ``START`` and
  ``END`` are UTF-8 byte offsets into the document text (the pivot for a span
  annotation kind anchored by a :class:`~lairs.records.defs.Span`).
- ``Rn<TAB>TYPE Arg1:Tx Arg2:Ty`` - a binary relation between two entities (the
  pivot for a relation annotation kind).
- ``An<TAB>TYPE Tx[ VALUE]`` - an attribute on an entity (a binary flag when no
  value is given), carried as annotation features.

The ``.txt`` and ``.ann`` are combined into a single source string separated by
a sentinel line so the codec round-trips both halves through one
:meth:`decode`/:meth:`encode` pair.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.integrations.codecs import CorpusFragment, FragmentRecord
from lairs.records._generated.annotation import (
    Annotation,
    AnnotationLayer,
    ArgumentRef,
)
from lairs.records._generated.defs import (
    Anchor,
    Feature,
    FeatureMap,
    ObjectRef,
    Span,
    Uuid,
)
from lairs.records._generated.expression import Expression

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from lairs._types import JsonValue

__all__ = ["BratCodec", "BratIso", "canonical_standoff"]

# the epoch timestamp used for the deterministic createdAt of generated layers,
# so that decode and encode round-trip without depending on wall-clock time.
_EPOCH = "1970-01-01T00:00:00+00:00"

# the sentinel separating the .txt half from the .ann half of a brat source.
_SEPARATOR = "\n===ANN===\n"

# the at-uri-shaped local reference the generated layers point at.
_EXPRESSION_REF = "at://local/expression"

# the nsid collections of the records a brat fragment carries.
_EXPRESSION_NSID = "pub.layers.expression"
_ANNOTATION_NSID = "pub.layers.annotation"

# the local ids of the records inside a brat fragment.
_EXPRESSION_LOCAL_ID = "expression"
_ENTITY_LAYER_LOCAL_ID = "entities"
_RELATION_LAYER_LOCAL_ID = "relations"


class BratCodec:
    """A bidirectional brat standoff codec.

    Decodes a combined ``.txt``/``.ann`` source into a
    :class:`~lairs.integrations.codecs.CorpusFragment` holding one expression
    record, a span :class:`~lairs.records.annotation.AnnotationLayer` for the
    text-bound entities, and (when relations are present) a relation layer.
    Encoding reverses the transform.
    """

    name = "brat"

    def decode(
        self,
        src: str | bytes,
        *,
        into: CorpusFragment | None = None,
    ) -> CorpusFragment:
        """Decode brat standoff into a corpus fragment.

        Parameters
        ----------
        src : str or bytes
            The combined ``.txt`` and ``.ann`` source, with the two halves
            separated by the brat sentinel line.
        into : lairs.integrations.codecs.CorpusFragment or None, optional
            An existing fragment to extend with the decoded records.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The decoded fragment.
        """
        text, ann = _split_source(_as_str(src))
        records = list(into.records) if into is not None else []
        records.extend(_records_from_standoff(_parse_standoff(text, ann)))
        return CorpusFragment(records=tuple(records), source=self.name)

    def encode(self, records: Iterable[FragmentRecord]) -> str:
        """Encode fragment records into brat standoff text.

        Parameters
        ----------
        records : collections.abc.Iterable of FragmentRecord
            The records to encode. The expression record supplies the ``.txt``
            half and the span/relation layers supply the ``.ann`` half.

        Returns
        -------
        str
            The combined ``.txt`` and ``.ann`` representation.
        """
        return _render_standoff(_standoff_from_records(tuple(records)))


class _Entity(dx.Model):
    """A parsed brat text-bound entity line.

    Parameters
    ----------
    tag : str
        The entity identifier (for example ``"T1"``).
    type_name : str
        The entity type label.
    byte_start : int
        The inclusive start UTF-8 byte offset.
    byte_end : int
        The exclusive end UTF-8 byte offset.
    text : str
        The covered surface text.
    """

    tag: str = dx.field(description="entity identifier such as T1")
    type_name: str = dx.field(description="entity type label")
    byte_start: int = dx.field(description="inclusive start byte offset")
    byte_end: int = dx.field(description="exclusive end byte offset")
    text: str = dx.field(description="covered surface text")


class _Relation(dx.Model):
    """A parsed brat relation line.

    Parameters
    ----------
    tag : str
        The relation identifier (for example ``"R1"``).
    type_name : str
        The relation type label.
    arg1 : str
        The first argument entity identifier.
    arg2 : str
        The second argument entity identifier.
    """

    tag: str = dx.field(description="relation identifier such as R1")
    type_name: str = dx.field(description="relation type label")
    arg1: str = dx.field(description="first argument entity tag")
    arg2: str = dx.field(description="second argument entity tag")


class _Attribute(dx.Model):
    """A parsed brat attribute line.

    Parameters
    ----------
    tag : str
        The attribute identifier (for example ``"A1"``).
    type_name : str
        The attribute type label.
    target : str
        The entity identifier the attribute applies to.
    value : str or None
        The attribute value, or ``None`` for a binary flag.
    """

    tag: str = dx.field(description="attribute identifier such as A1")
    type_name: str = dx.field(description="attribute type label")
    target: str = dx.field(description="entity tag the attribute applies to")
    value: str | None = dx.field(default=None, description="attribute value")


class _Standoff(dx.Model):
    """The fully parsed contents of a brat source.

    Parameters
    ----------
    text : str
        The document text.
    entities : tuple of _Entity
        The text-bound entities, in file order.
    relations : tuple of _Relation
        The relations, in file order.
    attributes : tuple of _Attribute
        The attributes, in file order.
    """

    text: str = dx.field(description="document text")
    entities: tuple[_Entity, ...] = dx.field(default=(), description="entities")
    relations: tuple[_Relation, ...] = dx.field(default=(), description="relations")
    attributes: tuple[_Attribute, ...] = dx.field(default=(), description="attributes")


class BratIso(dx.Iso[_Standoff, CorpusFragment]):
    """An :class:`~didactic.api.Iso` between a brat standoff and a fragment.

    The forward direction builds a corpus fragment from a parsed standoff; the
    backward direction recovers the standoff. Round-trip law fixtures verify
    that ``backward(forward(x)) == x`` on the supported subset (text-bound
    entities, binary relations, and attributes).
    """

    def forward(self, a: _Standoff, /) -> CorpusFragment:
        """Build a corpus fragment from a parsed standoff.

        Parameters
        ----------
        a : _Standoff
            The parsed brat contents.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The fragment of expression and annotation-layer records.
        """
        return CorpusFragment(
            records=tuple(_records_from_standoff(a)),
            source="brat",
        )

    def backward(self, b: CorpusFragment, /) -> _Standoff:
        """Recover a parsed standoff from a corpus fragment.

        Parameters
        ----------
        b : lairs.integrations.codecs.CorpusFragment
            The fragment to recover the standoff from.

        Returns
        -------
        _Standoff
            The parsed brat contents.
        """
        return _standoff_from_records(b.records)


def _as_str(src: str | bytes) -> str:
    """Return ``src`` decoded to text, treating bytes as UTF-8."""
    if isinstance(src, bytes):
        return src.decode("utf-8")
    return src


def _split_source(src: str) -> tuple[str, str]:
    """Split a combined source into its ``.txt`` and ``.ann`` halves."""
    if _SEPARATOR in src:
        text, ann = src.split(_SEPARATOR, 1)
        return text, ann
    # a bare source is treated as the .ann half over empty text.
    return "", src


def _parse_standoff(text: str, ann: str) -> _Standoff:
    """Parse the document text and ``.ann`` lines into a :class:`_Standoff`."""
    entities: list[_Entity] = []
    relations: list[_Relation] = []
    attributes: list[_Attribute] = []
    for raw in ann.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        kind = line[0]
        if kind == "T":
            entity = _parse_entity(line)
            if entity is not None:
                entities.append(entity)
        elif kind == "R":
            relation = _parse_relation(line)
            if relation is not None:
                relations.append(relation)
        elif kind == "A":
            attribute = _parse_attribute(line)
            if attribute is not None:
                attributes.append(attribute)
    return _Standoff(
        text=text,
        entities=tuple(entities),
        relations=tuple(relations),
        attributes=tuple(attributes),
    )


def _parse_entity(line: str) -> _Entity | None:
    """Parse a single ``T`` entity line, or ``None`` when malformed."""
    parts = line.split("\t")
    expected_fields = 3
    if len(parts) < expected_fields:
        return None
    tag = parts[0].strip()
    middle = parts[1].split()
    type_and_span = 3
    if len(middle) < type_and_span:
        return None
    type_name = middle[0]
    try:
        byte_start = int(middle[1])
        byte_end = int(middle[2])
    except ValueError:
        return None
    return _Entity(
        tag=tag,
        type_name=type_name,
        byte_start=byte_start,
        byte_end=byte_end,
        text=parts[2],
    )


def _parse_relation(line: str) -> _Relation | None:
    """Parse a single ``R`` relation line, or ``None`` when malformed."""
    parts = line.split("\t")
    expected_fields = 2
    if len(parts) < expected_fields:
        return None
    tag = parts[0].strip()
    middle = parts[1].split()
    type_and_args = 3
    if len(middle) < type_and_args:
        return None
    type_name = middle[0]
    arg1 = _arg_value(middle[1])
    arg2 = _arg_value(middle[2])
    if arg1 is None or arg2 is None:
        return None
    return _Relation(tag=tag, type_name=type_name, arg1=arg1, arg2=arg2)


def _parse_attribute(line: str) -> _Attribute | None:
    """Parse a single ``A`` attribute line, or ``None`` when malformed."""
    parts = line.split("\t")
    expected_fields = 2
    if len(parts) < expected_fields:
        return None
    tag = parts[0].strip()
    middle = parts[1].split()
    type_and_target = 2
    if len(middle) < type_and_target:
        return None
    type_name = middle[0]
    target = middle[1]
    value = middle[2] if len(middle) > type_and_target else None
    return _Attribute(tag=tag, type_name=type_name, target=target, value=value)


def _arg_value(token: str) -> str | None:
    """Return the entity tag from a ``Role:Tag`` relation argument token."""
    _, _, value = token.partition(":")
    return value or None


def _records_from_standoff(standoff: _Standoff) -> Iterator[FragmentRecord]:
    """Yield the fragment records for a parsed standoff."""
    yield FragmentRecord(
        local_id=_EXPRESSION_LOCAL_ID,
        nsid=_EXPRESSION_NSID,
        value_json=_expression_json(standoff.text),
    )
    yield FragmentRecord(
        local_id=_ENTITY_LAYER_LOCAL_ID,
        nsid=_ANNOTATION_NSID,
        value_json=_entity_layer_json(standoff),
    )
    if standoff.relations:
        yield FragmentRecord(
            local_id=_RELATION_LAYER_LOCAL_ID,
            nsid=_ANNOTATION_NSID,
            value_json=_relation_layer_json(standoff),
        )


def _expression_json(text: str) -> str:
    """Return the json for the expression record carrying the document text."""
    expression = Expression(
        id=_EXPRESSION_LOCAL_ID,
        kind="document",
        createdAt=_epoch(),
        text=text,
    )
    return expression.model_dump_json()


def _entity_layer_json(standoff: _Standoff) -> str:
    """Return the json for the span layer of text-bound entities."""
    attrs_by_target: dict[str, list[_Attribute]] = {}
    for attribute in standoff.attributes:
        attrs_by_target.setdefault(attribute.target, []).append(attribute)
    annotations = tuple(
        _entity_annotation(entity, attrs_by_target.get(entity.tag, []))
        for entity in standoff.entities
    )
    layer = AnnotationLayer(
        annotations=annotations,
        createdAt=_epoch(),
        expression=_EXPRESSION_REF,
        kind="span",
        formalism="brat",
    )
    return layer.model_dump_json()


def _relation_layer_json(standoff: _Standoff) -> str:
    """Return the json for the relation layer between entities."""
    annotations = tuple(
        _relation_annotation(relation) for relation in standoff.relations
    )
    layer = AnnotationLayer(
        annotations=annotations,
        createdAt=_epoch(),
        expression=_EXPRESSION_REF,
        kind="relation",
        formalism="brat",
    )
    return layer.model_dump_json()


def _entity_annotation(entity: _Entity, attrs: list[_Attribute]) -> Annotation:
    """Build a span annotation from a brat entity and its attributes."""
    return Annotation(
        uuid=Uuid(value=entity.tag),
        anchor=Anchor(
            textSpan=Span(byteStart=entity.byte_start, byteEnd=entity.byte_end)
        ),
        label=entity.type_name,
        text=entity.text,
        features=_features_for_entity(attrs),
    )


def _features_for_entity(attrs: list[_Attribute]) -> FeatureMap | None:
    """Build a feature map carrying an entity's brat attributes, if any."""
    if not attrs:
        return None
    entries = tuple(
        Feature(key=attribute.type_name, value=_attribute_value(attribute))
        for attribute in attrs
    )
    return FeatureMap(entries=entries)


def _attribute_value(attribute: _Attribute) -> str:
    """Return an attribute's value, defaulting a binary flag to ``"true"``."""
    return attribute.value if attribute.value is not None else "true"


def _relation_annotation(relation: _Relation) -> Annotation:
    """Build a relation annotation from a brat relation."""
    arguments = (
        ArgumentRef(role="Arg1", target=ObjectRef(localId=Uuid(value=relation.arg1))),
        ArgumentRef(role="Arg2", target=ObjectRef(localId=Uuid(value=relation.arg2))),
    )
    return Annotation(
        uuid=Uuid(value=relation.tag),
        label=relation.type_name,
        arguments=arguments,
    )


def _standoff_from_records(records: tuple[FragmentRecord, ...]) -> _Standoff:
    """Recover a parsed standoff from fragment records."""
    text = ""
    entities: list[_Entity] = []
    relations: list[_Relation] = []
    attributes: list[_Attribute] = []
    for record in records:
        value = json.loads(record.value_json)
        if not isinstance(value, dict):
            continue
        if record.nsid == _EXPRESSION_NSID:
            raw_text = value.get("text")
            if isinstance(raw_text, str):
                text = raw_text
        elif record.nsid == _ANNOTATION_NSID:
            _collect_layer(value, entities, relations, attributes)
    return _Standoff(
        text=text,
        entities=tuple(entities),
        relations=tuple(relations),
        attributes=tuple(attributes),
    )


def _collect_layer(
    value: dict[str, JsonValue],
    entities: list[_Entity],
    relations: list[_Relation],
    attributes: list[_Attribute],
) -> None:
    """Collect entities, relations, and attributes from a layer json mapping."""
    kind = value.get("kind")
    annotations = value.get("annotations")
    if not isinstance(annotations, list):
        return
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        if kind == "span":
            entity = _entity_from_annotation(annotation)
            if entity is not None:
                entities.append(entity)
                for type_name, attr_value in _attribute_pairs(annotation):
                    attributes.append(
                        _Attribute(
                            tag=f"A{len(attributes) + 1}",
                            type_name=type_name,
                            target=entity.tag,
                            value=attr_value,
                        )
                    )
        elif kind == "relation":
            relation = _relation_from_annotation(annotation)
            if relation is not None:
                relations.append(relation)


def _entity_from_annotation(annotation: dict[str, JsonValue]) -> _Entity | None:
    """Recover a brat entity from a span annotation json mapping."""
    tag = _uuid_value(annotation.get("uuid"))
    anchor = annotation.get("anchor")
    label = annotation.get("label")
    text = annotation.get("text")
    if tag is None or not isinstance(anchor, dict) or not isinstance(label, str):
        return None
    span = anchor.get("textSpan")
    if not isinstance(span, dict):
        return None
    byte_start = span.get("byteStart")
    byte_end = span.get("byteEnd")
    if not isinstance(byte_start, int) or not isinstance(byte_end, int):
        return None
    return _Entity(
        tag=tag,
        type_name=label,
        byte_start=byte_start,
        byte_end=byte_end,
        text=text if isinstance(text, str) else "",
    )


def _attribute_pairs(
    annotation: dict[str, JsonValue],
) -> Iterator[tuple[str, str | None]]:
    """Yield ``(type_name, value)`` pairs from a span annotation's features.

    A feature value of ``"true"`` is recovered as a binary flag (``None``);
    any other value is recovered verbatim.
    """
    features = annotation.get("features")
    if not isinstance(features, dict):
        return
    entries = features.get("entries")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        raw_value = entry.get("value")
        if not isinstance(key, str):
            continue
        value = None if raw_value == "true" else raw_value
        yield key, value if isinstance(value, str) else None


def _relation_from_annotation(annotation: dict[str, JsonValue]) -> _Relation | None:
    """Recover a brat relation from a relation annotation json mapping."""
    tag = _uuid_value(annotation.get("uuid"))
    label = annotation.get("label")
    arguments = annotation.get("arguments")
    if tag is None or not isinstance(label, str) or not isinstance(arguments, list):
        return None
    arg_pair = 2
    if len(arguments) < arg_pair:
        return None
    arg1 = _argument_target(arguments[0])
    arg2 = _argument_target(arguments[1])
    if arg1 is None or arg2 is None:
        return None
    return _Relation(tag=tag, type_name=label, arg1=arg1, arg2=arg2)


def _argument_target(argument: JsonValue) -> str | None:
    """Recover the target entity tag from an argument json mapping."""
    if not isinstance(argument, dict):
        return None
    target = argument.get("target")
    if not isinstance(target, dict):
        return None
    return _uuid_value(target.get("localId"))


def _uuid_value(value: JsonValue) -> str | None:
    """Recover the string value of a uuid json mapping."""
    if not isinstance(value, dict):
        return None
    inner = value.get("value")
    return inner if isinstance(inner, str) else None


def _render_standoff(standoff: _Standoff) -> str:
    """Render a parsed standoff to a combined brat source string."""
    lines = [_render_entity(entity) for entity in standoff.entities]
    lines.extend(_render_relation(relation) for relation in standoff.relations)
    lines.extend(_render_attribute(attribute) for attribute in standoff.attributes)
    ann = "\n".join(lines)
    return f"{standoff.text}{_SEPARATOR}{ann}"


def _render_entity(entity: _Entity) -> str:
    """Render a brat entity back to a ``T`` line."""
    return (
        f"{entity.tag}\t{entity.type_name} "
        f"{entity.byte_start} {entity.byte_end}\t{entity.text}"
    )


def _render_relation(relation: _Relation) -> str:
    """Render a brat relation back to an ``R`` line."""
    return (
        f"{relation.tag}\t{relation.type_name} "
        f"Arg1:{relation.arg1} Arg2:{relation.arg2}"
    )


def _render_attribute(attribute: _Attribute) -> str:
    """Render a brat attribute back to an ``A`` line."""
    suffix = f" {attribute.value}" if attribute.value is not None else ""
    return f"{attribute.tag}\t{attribute.type_name} {attribute.target}{suffix}"


def canonical_standoff(standoff: _Standoff) -> _Standoff:
    """Return a standoff in the codec's canonical, round-trippable form.

    The brat codec preserves a standoff's text, entity geometry, and relations
    exactly, but normalises identifiers and groups attributes under their
    target entity. Entity tags become ``T1..Tn`` in declaration order, relation
    tags become ``R1..Rn``, and attribute tags become ``A1..An`` ordered by the
    entity they decorate. Round-trip law fixtures sample from this canonical
    subset, on which ``BratIso.backward(BratIso.forward(x)) == x`` holds.

    Parameters
    ----------
    standoff : _Standoff
        Any parsed standoff.

    Returns
    -------
    _Standoff
        The canonicalised standoff.
    """
    tag_map: dict[str, str] = {}
    entities: list[_Entity] = []
    for index, entity in enumerate(standoff.entities):
        new_tag = f"T{index + 1}"
        tag_map[entity.tag] = new_tag
        entities.append(entity.with_(tag=new_tag))
    relations: list[_Relation] = []
    for index, relation in enumerate(standoff.relations):
        relations.append(
            relation.with_(
                tag=f"R{index + 1}",
                arg1=tag_map.get(relation.arg1, relation.arg1),
                arg2=tag_map.get(relation.arg2, relation.arg2),
            )
        )
    attributes: list[_Attribute] = []
    for entity in entities:
        original = _original_tag(tag_map, entity.tag)
        for attribute in standoff.attributes:
            if attribute.target != original:
                continue
            attributes.append(
                attribute.with_(
                    tag=f"A{len(attributes) + 1}",
                    target=entity.tag,
                )
            )
    return _Standoff(
        text=standoff.text,
        entities=tuple(entities),
        relations=tuple(relations),
        attributes=tuple(attributes),
    )


def _original_tag(tag_map: dict[str, str], new_tag: str) -> str:
    """Return the pre-canonical tag that maps to ``new_tag``."""
    for old, new in tag_map.items():
        if new == new_tag:
            return old
    return new_tag


def _epoch() -> datetime:
    """Return the deterministic epoch datetime used for generated records."""
    return datetime.fromisoformat(_EPOCH)
