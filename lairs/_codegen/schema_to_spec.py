"""Walk a panproto Schema into lairs codegen spec models.

The parsed ``Schema`` retains union discriminators, refined value types, the
reference-versus-containment edge distinction, and integer ranges, all of which
the lossy ``theory_of`` path would drop. The lexicon JSON document retains the
field descriptions and the ``required`` set that panproto does not surface. This
module fuses both sources into a sequence of :class:`ModelSpec` value models,
one per record or object definition and one per formal union definition, which
the emitter renders to committed Python module text.

Notes
-----
Every spec type here is a ``dx.Model``; the codegen intermediate representation
is data, like everything else in lairs. The synthesised-model round-trip path
(``didactic.models_from_specs``) is intentionally not used for emission because
it discards descriptions, defaults, optionality, refined value types, and the
reference-versus-embed distinction. The emitter renders the rich spec directly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Sequence

    from panproto import Schema

    from lairs._types import JsonValue

__all__ = [
    "FieldSpec",
    "ModelSpec",
    "VariantSpec",
    "schema_to_specs",
]

# the four lexicon string formats that map to a refined python type or carry a
# semantic alias in field metadata. only ``datetime`` changes the python type;
# the rest stay ``str`` with the format recorded.
_DATETIME_FORMAT = "datetime"


class FieldSpec(dx.Model):
    """A single field of a generated model.

    Attributes
    ----------
    name : str
        The lexicon property name, used verbatim as the python attribute name.
    type_kind : str
        The resolved field shape, one of ``"str"``, ``"int"``, ``"bool"``,
        ``"datetime"``, ``"bytes"``, ``"blob"``, ``"embed"``, ``"union"``,
        ``"array"``, or ``"unknown"``.
    target : str or None, optional
        For ``"embed"`` and ``"union"`` kinds, the name of the referenced model
        or union class. ``None`` for scalar kinds.
    item : lairs._codegen.schema_to_spec.FieldSpec or None, optional
        For the ``"array"`` kind, the spec of the element type. ``None``
        otherwise.
    required : bool, optional
        Whether the lexicon lists this property in its ``required`` set.
    description : str or None, optional
        The lexicon ``description`` for the property, recorded as field
        metadata.
    string_format : str or None, optional
        The lexicon ``format`` of a string field (for example ``"at-uri"`` or
        ``"did"``), recorded as field metadata.
    known_values : tuple of str, optional
        The lexicon ``knownValues`` of an open string enum, recorded as field
        metadata; never a hard enum.
    minimum : int or None, optional
        The lexicon ``minimum`` of an integer field, recorded as field
        metadata.
    maximum : int or None, optional
        The lexicon ``maximum`` of an integer field, recorded as field
        metadata.
    min_length : int or None, optional
        The lexicon ``minLength`` of a string field, recorded as field
        metadata.
    max_length : int or None, optional
        The lexicon ``maxLength`` of a string field, recorded as field
        metadata.
    """

    name: str = dx.field(description="lexicon property name")
    type_kind: str = dx.field(description="resolved field shape")
    target: str | None = dx.field(
        default=None,
        description="referenced model or union class name, for embed and union",
    )
    item: FieldSpec | None = dx.field(
        default=None,
        description="element spec for the array kind",
    )
    required: bool = dx.field(
        default=False,
        description="whether the lexicon marks the property required",
    )
    description: str | None = dx.field(
        default=None,
        description="lexicon description recorded as field metadata",
    )
    string_format: str | None = dx.field(
        default=None,
        description="lexicon string format recorded as field metadata",
    )
    known_values: tuple[str, ...] = dx.field(
        default=(),
        description="lexicon knownValues recorded as field metadata",
    )
    minimum: int | None = dx.field(
        default=None,
        description="lexicon integer minimum recorded as field metadata",
    )
    maximum: int | None = dx.field(
        default=None,
        description="lexicon integer maximum recorded as field metadata",
    )
    min_length: int | None = dx.field(
        default=None,
        description="lexicon string minLength recorded as field metadata",
    )
    max_length: int | None = dx.field(
        default=None,
        description="lexicon string maxLength recorded as field metadata",
    )


class VariantSpec(dx.Model):
    """A single member of a formal union definition.

    Attributes
    ----------
    discriminator_value : str
        The value the union discriminator takes for this variant, derived from
        the member reference shortname.
    class_name : str
        The python class name of the variant model.
    target : str
        The name of the embedded member model the variant wraps.
    """

    discriminator_value: str = dx.field(
        description="discriminator value for the member"
    )
    class_name: str = dx.field(description="python class name of the variant")
    target: str = dx.field(description="embedded member model name")


class ModelSpec(dx.Model):
    """A generated model or union, ready for emission.

    Attributes
    ----------
    name : str
        The python class name (the capitalised lexicon definition shortname).
    nsid : str
        The source lexicon namespace identifier (for example
        ``"pub.layers.defs"``).
    def_name : str
        The lexicon definition shortname (for example ``"span"`` or
        ``"main"``).
    is_record : bool, optional
        Whether the definition is a top-level ``record`` (def ``main``) rather
        than a nested ``object``.
    is_union : bool, optional
        Whether the definition is a formal ``union`` rendered as a
        ``dx.TaggedUnion``.
    discriminator : str or None, optional
        For unions, the discriminator field name.
    description : str or None, optional
        The lexicon ``description`` of the definition, used as the class
        docstring summary.
    fields : tuple of lairs._codegen.schema_to_spec.FieldSpec, optional
        The model fields, for non-union models.
    variants : tuple of lairs._codegen.schema_to_spec.VariantSpec, optional
        The union members, for unions.
    """

    name: str = dx.field(description="python class name")
    nsid: str = dx.field(description="source lexicon namespace identifier")
    def_name: str = dx.field(description="lexicon definition shortname")
    is_record: bool = dx.field(
        default=False,
        description="whether the definition is a top-level record",
    )
    is_union: bool = dx.field(
        default=False,
        description="whether the definition is a formal union",
    )
    discriminator: str | None = dx.field(
        default=None,
        description="union discriminator field name",
    )
    description: str | None = dx.field(
        default=None,
        description="lexicon description of the definition",
    )
    fields: tuple[FieldSpec, ...] = dx.field(
        default=(),
        description="model fields, for non-union models",
    )
    variants: tuple[VariantSpec, ...] = dx.field(
        default=(),
        description="union members, for unions",
    )


def schema_to_specs(
    schema: Schema,
    document: dict[str, JsonValue],
) -> Sequence[ModelSpec]:
    """Map a parsed Schema plus its lexicon document to codegen spec models.

    Parameters
    ----------
    schema : panproto.Schema
        A Schema parsed from a lexicon document under the atproto protocol.
    document : dict
        The raw lexicon JSON document the Schema was parsed from. It supplies
        the ``required`` sets and field descriptions that the Schema graph does
        not surface.

    Returns
    -------
    collections.abc.Sequence of lairs._codegen.schema_to_spec.ModelSpec
        One spec per record, object, and formal union definition in the
        lexicon, with descriptions, optionality, refined types, integer ranges,
        knownValues, and union discriminators preserved. Method definitions
        (query, procedure, subscription) are skipped.
    """
    nsid = _document_nsid(document)
    defs = _document_defs(document)
    if _is_method_document(defs):
        # a method lexicon (query, procedure, subscription) contributes no
        # record models; its nested objects (for example recordView) are part
        # of the wire envelope, not the record surface, so the whole document
        # is skipped
        return ()
    # the parsed schema is accepted to assert the document parses cleanly and
    # to keep the union-discriminator round-trip contract; the spec mapping
    # itself reads the lexicon document, which carries the required sets and
    # descriptions the schema graph does not surface
    _ = schema
    specs: list[ModelSpec] = []
    for def_name, definition in defs.items():
        def_type = _string_value(definition.get("type"))
        if def_type == "record":
            specs.append(_record_spec(nsid, def_name, definition))
        elif def_type == "object":
            specs.extend(_object_specs(nsid, def_name, definition))
    return tuple(specs)


def _is_method_document(defs: dict[str, dict[str, JsonValue]]) -> bool:
    """Return whether a lexicon's ``main`` definition is an XRPC method."""
    main = defs.get("main", {})
    return _string_value(main.get("type")) in {"query", "procedure", "subscription"}


def _record_spec(
    nsid: str,
    def_name: str,
    definition: dict[str, JsonValue],
) -> ModelSpec:
    """Build the spec for a record definition (``def main``)."""
    record = _mapping_value(definition.get("record"))
    fields = _field_specs(nsid, record)
    return ModelSpec(
        name=_class_name(nsid, def_name),
        nsid=nsid,
        def_name=def_name,
        is_record=True,
        description=_string_or_none(definition.get("description")),
        fields=fields,
    )


def _object_specs(
    nsid: str,
    def_name: str,
    definition: dict[str, JsonValue],
) -> Sequence[ModelSpec]:
    """Build the specs for an object definition and any inline union property.

    An object property typed ``union`` (a formal closed/open union over refs)
    is emitted as its own ``dx.TaggedUnion`` model alongside the owning object.
    """
    extra: list[ModelSpec] = []
    fields: list[FieldSpec] = []
    properties = _mapping_value(definition.get("properties"))
    required = _required_set(definition)
    for prop_name, prop in sorted(properties.items()):
        prop_map = _mapping_value(prop)
        if _string_value(prop_map.get("type")) == "union":
            union_spec = _union_spec(nsid, def_name, prop_name, prop_map)
            extra.append(union_spec)
            fields.append(
                FieldSpec(
                    name=prop_name,
                    type_kind="union",
                    target=union_spec.name,
                    required=prop_name in required,
                    description=_string_or_none(prop_map.get("description")),
                )
            )
        else:
            fields.append(
                _field_spec(nsid, prop_name, prop_map, required=prop_name in required)
            )
    owner = ModelSpec(
        name=_class_name(nsid, def_name),
        nsid=nsid,
        def_name=def_name,
        description=_string_or_none(definition.get("description")),
        fields=tuple(fields),
    )
    # emit union members before the owner so the owner's embed resolves
    return (*extra, owner)


def _union_spec(
    nsid: str,
    owner_def: str,
    prop_name: str,
    prop: dict[str, JsonValue],
) -> ModelSpec:
    """Build the spec for a formal union property as a tagged union.

    The discriminator value of each variant is the member reference shortname
    (for example ``"textQuoteSelector"``), matching the lexicon ``refs`` order.
    """
    union_name = _union_class_name(nsid, owner_def, prop_name)
    refs = _string_list(prop.get("refs"))
    variants: list[VariantSpec] = []
    for ref in refs:
        member = _ref_shortname(ref)
        variants.append(
            VariantSpec(
                discriminator_value=member,
                class_name=f"{union_name}{_capitalise(member)}",
                target=_class_name(nsid, member),
            )
        )
    return ModelSpec(
        name=union_name,
        nsid=nsid,
        def_name=f"{owner_def}.{prop_name}",
        is_union=True,
        discriminator="kind",
        description=_string_or_none(prop.get("description")),
        variants=tuple(variants),
    )


def _field_specs(
    nsid: str,
    container: dict[str, JsonValue],
) -> tuple[FieldSpec, ...]:
    """Build field specs for the properties of a record body or object."""
    properties = _mapping_value(container.get("properties"))
    required = _required_set(container)
    fields = [
        _field_spec(
            nsid, prop_name, _mapping_value(prop), required=prop_name in required
        )
        for prop_name, prop in sorted(properties.items())
    ]
    return tuple(fields)


# lexicon scalar types that map directly to a field type-kind with no extra
# structure. ``cid-link`` and the empty type collapse to a plain string.
_SCALAR_TYPE_KINDS: dict[str, str] = {
    "blob": "blob",
    "bytes": "bytes",
    "boolean": "bool",
}


def _field_spec(
    nsid: str,
    name: str,
    prop: dict[str, JsonValue],
    *,
    required: bool,
) -> FieldSpec:
    """Map one lexicon property to a field spec."""
    prop_type = _string_value(prop.get("type"))
    description = _string_or_none(prop.get("description"))
    if prop_type == "ref":
        return _ref_field(nsid, name, prop, required=required, description=description)
    if prop_type == "array":
        item = _field_spec(nsid, name, _mapping_value(prop.get("items")), required=True)
        return FieldSpec(
            name=name,
            type_kind="array",
            item=item,
            required=required,
            description=description,
        )
    if prop_type == "integer":
        return FieldSpec(
            name=name,
            type_kind="int",
            required=required,
            description=description,
            minimum=_int_or_none(prop.get("minimum")),
            maximum=_int_or_none(prop.get("maximum")),
        )
    if prop_type in _SCALAR_TYPE_KINDS:
        return FieldSpec(
            name=name,
            type_kind=_SCALAR_TYPE_KINDS[prop_type],
            required=required,
            description=description,
        )
    # string, cid-link, the empty type, and any unknown construct all map to a
    # string-shaped field so the generated record validates rather than failing
    return _string_field(name, prop, required=required, description=description)


def _ref_field(
    nsid: str,
    name: str,
    prop: dict[str, JsonValue],
    *,
    required: bool,
    description: str | None,
) -> FieldSpec:
    """Map a lexicon ``ref`` property to an embed field spec.

    A ``ref`` inside a record or object always points at a ``defs#object``
    type (cross-record links use ``format: at-uri`` strings instead), so it is
    rendered as an embed of the target model.
    """
    ref = _string_value(prop.get("ref"))
    target = _ref_shortname(ref)
    return FieldSpec(
        name=name,
        type_kind="embed",
        target=_class_name(nsid, target, qualified_ref=ref),
        required=required,
        description=description,
    )


def _string_field(
    name: str,
    prop: dict[str, JsonValue],
    *,
    required: bool,
    description: str | None,
) -> FieldSpec:
    """Map a string-typed (or cid-link) lexicon property to a field spec.

    A ``datetime`` format refines the python type to ``datetime``; every other
    format (``at-uri``, ``uri``, ``did``, ``at-identifier``, ``cid``) stays a
    ``str`` with the format recorded in field metadata.
    """
    fmt = _string_or_none(prop.get("format"))
    type_kind = "datetime" if fmt == _DATETIME_FORMAT else "str"
    return FieldSpec(
        name=name,
        type_kind=type_kind,
        required=required,
        description=description,
        string_format=fmt,
        known_values=_string_tuple(prop.get("knownValues")),
        min_length=_int_or_none(prop.get("minLength")),
        max_length=_int_or_none(prop.get("maxLength")),
    )


# ---------------------------------------------------------------------------
# document and value helpers
# ---------------------------------------------------------------------------


def _document_nsid(document: dict[str, JsonValue]) -> str:
    """Return the lexicon namespace identifier from a document."""
    return _string_value(document.get("id"))


def _document_defs(document: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    """Return the ordered definition mapping from a lexicon document."""
    defs = _mapping_value(document.get("defs"))
    return {name: _mapping_value(value) for name, value in defs.items()}


def _required_set(container: dict[str, JsonValue]) -> frozenset[str]:
    """Return the set of required property names from a container."""
    return frozenset(_string_list(container.get("required")))


def _class_name(nsid: str, def_name: str, *, qualified_ref: str = "") -> str:
    """Return the python class name for a definition or ref target.

    A ``main`` record definition is named after its lexicon's last component
    (for example ``pub.layers.expression.expression#main`` -> ``Expression``).
    Every other definition is named after its capitalised shortname. A fully
    qualified cross-file ref ending in ``#main`` resolves to the target
    lexicon's record name.
    """
    if qualified_ref and "#" in qualified_ref and not qualified_ref.startswith("#"):
        target_nsid, _, fragment = qualified_ref.partition("#")
        if fragment == "main":
            return _capitalise(target_nsid.rsplit(".", 1)[-1])
        return _capitalise(fragment)
    if def_name == "main":
        return _capitalise(nsid.rsplit(".", 1)[-1])
    return _capitalise(def_name)


def _union_class_name(nsid: str, owner_def: str, prop_name: str) -> str:
    """Return the python class name for a formal union property."""
    owner = _class_name(nsid, owner_def)
    return f"{owner}{_capitalise(prop_name)}"


def _ref_shortname(ref: str) -> str:
    """Return the fragment shortname of a lexicon ref string."""
    _, _, fragment = ref.partition("#")
    return fragment or ref


def _capitalise(name: str) -> str:
    """Return ``name`` with its first character upper-cased, rest preserved."""
    if not name:
        return name
    return name[0].upper() + name[1:]


def _string_value(value: JsonValue) -> str:
    """Return ``value`` as a string, or the empty string when absent."""
    return value if isinstance(value, str) else ""


def _string_or_none(value: JsonValue) -> str | None:
    """Return ``value`` as a string, or ``None`` when absent."""
    return value if isinstance(value, str) else None


def _int_or_none(value: JsonValue) -> int | None:
    """Return ``value`` as an int, or ``None`` when absent."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _mapping_value(value: JsonValue) -> dict[str, JsonValue]:
    """Return ``value`` as a string-keyed mapping, or an empty mapping."""
    return value if isinstance(value, dict) else {}


def _string_list(value: JsonValue) -> list[str]:
    """Return ``value`` as a list of strings, dropping non-string elements."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_tuple(value: JsonValue) -> tuple[str, ...]:
    """Return a lexicon knownValues field as a tuple of strings.

    The constraint is carried either as a real JSON array or, in the panproto
    constraint surface, as a JSON-encoded string; both shapes are accepted.
    """
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    if isinstance(value, str):
        decoded = _decode_json_array(value)
        return tuple(item for item in decoded if isinstance(item, str))
    return ()


def _decode_json_array(text: str) -> list[JsonValue]:
    """Decode a JSON array string, returning an empty list on failure."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
