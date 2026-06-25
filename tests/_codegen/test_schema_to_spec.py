"""Unit tests for lairs._codegen.schema_to_spec."""

from __future__ import annotations

from typing import TYPE_CHECKING

import panproto as pp

from lairs._codegen import schema_to_spec
from lairs._codegen.schema_to_spec import ModelSpec, schema_to_specs

if TYPE_CHECKING:
    from lairs._types import JsonValue

_RECORD_DOC: dict[str, JsonValue] = {
    "lexicon": 1,
    "id": "pub.layers.demo.demo",
    "defs": {
        "main": {
            "type": "record",
            "key": "tid",
            "record": {
                "type": "object",
                "required": ["text", "createdAt"],
                "properties": {
                    "text": {"type": "string", "description": "the text"},
                    "count": {"type": "integer", "minimum": 0, "maximum": 9},
                    "createdAt": {"type": "string", "format": "datetime"},
                    "uri": {"type": "string", "format": "at-uri"},
                    "kind": {
                        "type": "string",
                        "knownValues": ["a", "b"],
                        "maxLength": 8,
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "flag": {"type": "boolean"},
                },
            },
        },
    },
}


def _parse(document: dict[str, JsonValue]) -> pp.Schema:
    return pp.parse_atproto_lexicon(document)


def test_exports() -> None:
    assert set(schema_to_spec.__all__) == {
        "FieldSpec",
        "ModelSpec",
        "VariantSpec",
        "schema_to_specs",
    }


def test_record_becomes_a_record_spec() -> None:
    document = _RECORD_DOC
    specs = schema_to_specs(_parse(document), document)
    records = [spec for spec in specs if spec.is_record]
    assert len(records) == 1
    record = records[0]
    assert record.name == "Demo"
    assert record.is_record is True


def test_field_kinds_and_optionality() -> None:
    document = _RECORD_DOC
    specs = schema_to_specs(_parse(document), document)
    record = next(spec for spec in specs if spec.is_record)
    by_name = {field.name: field for field in record.fields}
    assert by_name["text"].type_kind == "str"
    assert by_name["text"].required is True
    assert by_name["text"].description == "the text"
    assert by_name["count"].type_kind == "int"
    assert by_name["count"].required is False
    assert by_name["count"].minimum == 0
    assert by_name["count"].maximum == 9
    assert by_name["createdAt"].type_kind == "datetime"
    assert by_name["createdAt"].required is True
    assert by_name["uri"].type_kind == "str"
    assert by_name["uri"].string_format == "at-uri"
    assert by_name["kind"].known_values == ("a", "b")
    assert by_name["kind"].max_length == 8
    assert by_name["flag"].type_kind == "bool"


def test_array_field_carries_element_spec() -> None:
    document = _RECORD_DOC
    specs = schema_to_specs(_parse(document), document)
    record = next(spec for spec in specs if spec.is_record)
    tags = next(field for field in record.fields if field.name == "tags")
    assert tags.type_kind == "array"
    assert tags.item is not None
    assert tags.item.type_kind == "str"


def test_ref_property_becomes_an_embed() -> None:
    document: dict[str, JsonValue] = {
        "lexicon": 1,
        "id": "pub.layers.demo.demo",
        "defs": {
            "main": {
                "type": "record",
                "key": "tid",
                "record": {
                    "type": "object",
                    "required": [],
                    "properties": {"inner": {"type": "ref", "ref": "#inner"}},
                },
            },
            "inner": {
                "type": "object",
                "required": ["x"],
                "properties": {"x": {"type": "string"}},
            },
        },
    }
    specs = schema_to_specs(_parse(document), document)
    record = next(spec for spec in specs if spec.is_record)
    inner = next(field for field in record.fields if field.name == "inner")
    assert inner.type_kind == "embed"
    assert inner.target == "Inner"


def test_blob_property_becomes_a_blob_field() -> None:
    document: dict[str, JsonValue] = {
        "lexicon": 1,
        "id": "pub.layers.demo.demo",
        "defs": {
            "main": {
                "type": "record",
                "key": "tid",
                "record": {
                    "type": "object",
                    "required": [],
                    "properties": {
                        "media": {"type": "blob", "accept": ["*/*"], "maxSize": 1000},
                    },
                },
            },
        },
    }
    specs = schema_to_specs(_parse(document), document)
    record = next(spec for spec in specs if spec.is_record)
    media = next(field for field in record.fields if field.name == "media")
    assert media.type_kind == "blob"


def test_union_property_becomes_a_tagged_union_spec() -> None:
    document: dict[str, JsonValue] = {
        "lexicon": 1,
        "id": "pub.layers.demo.demo",
        "defs": {
            "holder": {
                "type": "object",
                "required": [],
                "properties": {
                    "selector": {
                        "type": "union",
                        "refs": ["#alpha", "#beta"],
                    },
                },
            },
            "alpha": {
                "type": "object",
                "required": [],
                "properties": {"a": {"type": "string"}},
            },
            "beta": {
                "type": "object",
                "required": [],
                "properties": {"b": {"type": "string"}},
            },
        },
    }
    specs = schema_to_specs(_parse(document), document)
    unions = [spec for spec in specs if spec.is_union]
    assert len(unions) == 1
    union = unions[0]
    assert union.discriminator == "kind"
    values = [variant.discriminator_value for variant in union.variants]
    assert values == ["alpha", "beta"]
    targets = [variant.target for variant in union.variants]
    assert targets == ["Alpha", "Beta"]


def test_record_body_inline_union_becomes_a_tagged_union_spec() -> None:
    document: dict[str, JsonValue] = {
        "lexicon": 1,
        "id": "pub.layers.demo.demo",
        "defs": {
            "main": {
                "type": "record",
                "key": "tid",
                "record": {
                    "type": "object",
                    "required": [],
                    "properties": {
                        "selector": {
                            "type": "union",
                            "refs": ["#alpha", "#beta"],
                        },
                    },
                },
            },
            "alpha": {
                "type": "object",
                "required": [],
                "properties": {"a": {"type": "string"}},
            },
            "beta": {
                "type": "object",
                "required": [],
                "properties": {"b": {"type": "string"}},
            },
        },
    }
    specs = schema_to_specs(_parse(document), document)
    unions = [spec for spec in specs if spec.is_union]
    assert len(unions) == 1
    union = unions[0]
    assert union.name == "DemoSelector"
    assert [variant.discriminator_value for variant in union.variants] == [
        "alpha",
        "beta",
    ]
    record = next(spec for spec in specs if spec.is_record)
    selector = next(field for field in record.fields if field.name == "selector")
    assert selector.type_kind == "union"
    assert selector.target == "DemoSelector"


def test_array_of_union_becomes_a_tagged_union_element() -> None:
    document: dict[str, JsonValue] = {
        "lexicon": 1,
        "id": "pub.layers.demo.demo",
        "defs": {
            "holder": {
                "type": "object",
                "required": [],
                "properties": {
                    "selectors": {
                        "type": "array",
                        "items": {"type": "union", "refs": ["#alpha", "#beta"]},
                    },
                },
            },
            "alpha": {
                "type": "object",
                "required": [],
                "properties": {"a": {"type": "string"}},
            },
            "beta": {
                "type": "object",
                "required": [],
                "properties": {"b": {"type": "string"}},
            },
        },
    }
    specs = schema_to_specs(_parse(document), document)
    unions = [spec for spec in specs if spec.is_union]
    assert len(unions) == 1
    assert unions[0].name == "HolderSelectors"
    holder = next(spec for spec in specs if spec.name == "Holder")
    selectors = next(field for field in holder.fields if field.name == "selectors")
    assert selectors.type_kind == "array"
    assert selectors.item is not None
    assert selectors.item.type_kind == "union"
    assert selectors.item.target == "HolderSelectors"


def test_cross_file_union_member_resolves_to_target_class() -> None:
    document: dict[str, JsonValue] = {
        "lexicon": 1,
        "id": "pub.layers.demo.demo",
        "defs": {
            "holder": {
                "type": "object",
                "required": [],
                "properties": {
                    "selector": {
                        "type": "union",
                        "refs": [
                            "pub.layers.other#thing",
                            "pub.layers.other.widget#main",
                        ],
                    },
                },
            },
        },
    }
    specs = schema_to_specs(_parse(document), document)
    union = next(spec for spec in specs if spec.is_union)
    targets = [variant.target for variant in union.variants]
    # the fragment ref resolves to its capitalised shortname; the #main ref
    # resolves to the target lexicon's record name, not the owner's
    assert targets == ["Thing", "Widget"]


def test_method_documents_are_skipped() -> None:
    document: dict[str, JsonValue] = {
        "lexicon": 1,
        "id": "pub.layers.demo.listThings",
        "defs": {
            "main": {
                "type": "query",
                "output": {"encoding": "application/json"},
            },
            "recordView": {
                "type": "object",
                "required": [],
                "properties": {"uri": {"type": "string"}},
            },
        },
    }
    specs = schema_to_specs(_parse(document), document)
    assert specs == ()


def test_model_spec_round_trips() -> None:
    document = _RECORD_DOC
    specs = schema_to_specs(_parse(document), document)
    record = next(spec for spec in specs if spec.is_record)
    assert ModelSpec.model_validate(record.model_dump()) == record


def test_string_tuple_decodes_a_json_encoded_array() -> None:
    # the panproto constraint surface carries knownValues as a JSON string
    assert schema_to_spec._string_tuple('["a", "b", "c"]') == ("a", "b", "c")


def test_string_tuple_accepts_a_real_json_array() -> None:
    assert schema_to_spec._string_tuple(["x", 1, "y"]) == ("x", "y")


def test_string_tuple_empty_on_non_array_value() -> None:
    assert schema_to_spec._string_tuple(42) == ()


def test_decode_json_array_returns_empty_on_invalid_json() -> None:
    assert schema_to_spec._decode_json_array("not json") == []


def test_decode_json_array_returns_empty_on_non_array_json() -> None:
    assert schema_to_spec._decode_json_array('{"k": 1}') == []


def test_class_name_cross_file_main_resolves_to_target_record() -> None:
    name = schema_to_spec._class_name(
        "pub.layers.demo",
        "thing",
        qualified_ref="pub.layers.other.widget#main",
    )
    assert name == "Widget"


def test_class_name_cross_file_fragment_resolves_to_shortname() -> None:
    name = schema_to_spec._class_name(
        "pub.layers.demo",
        "thing",
        qualified_ref="pub.layers.other#thing",
    )
    assert name == "Thing"


def test_class_name_local_main_resolves_to_namespace_record() -> None:
    assert schema_to_spec._class_name("pub.layers.expression.expression", "main") == (
        "Expression"
    )
