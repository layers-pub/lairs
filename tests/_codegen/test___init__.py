"""Unit tests for the lairs._codegen package surface."""

from __future__ import annotations

import lairs._codegen as mod


def test_public_surface() -> None:
    assert set(mod.__all__) == {
        "FieldSpec",
        "Manifest",
        "ModelSpec",
        "VariantSpec",
        "check",
        "emit_module",
        "generate",
        "load_manifest",
        "namespace_specs",
        "schema_to_specs",
    }


def test_callables_are_exported() -> None:
    assert callable(mod.generate)
    assert callable(mod.check)
    assert callable(mod.schema_to_specs)
    assert callable(mod.emit_module)
