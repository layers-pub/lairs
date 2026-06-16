"""Unit tests for lairs._codegen.schema_to_spec."""

from __future__ import annotations

import pytest

from lairs._codegen import schema_to_spec


def test_exports() -> None:
    assert set(schema_to_spec.__all__) == {"schema_to_specs"}


def test_schema_to_specs_is_a_stub() -> None:
    panproto = pytest.importorskip("panproto")
    schema = panproto.parse_atproto_lexicon(
        {
            "lexicon": 1,
            "id": "pub.layers.demo",
            "defs": {
                "main": {
                    "type": "record",
                    "key": "tid",
                    "record": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {"text": {"type": "string"}},
                    },
                },
            },
        },
    )
    with pytest.raises(NotImplementedError):
        schema_to_spec.schema_to_specs(schema)
