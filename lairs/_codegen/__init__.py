"""Codegen pipeline that turns vendored lexicons into generated models.

The pipeline parses each lexicon into a panproto ``Schema``, walks it into
didactic spec dicts, builds models, and emits Python module text.
"""

from __future__ import annotations

from lairs._codegen.emit import emit_module
from lairs._codegen.manifest import Manifest, load_manifest
from lairs._codegen.pipeline import check, generate, namespace_specs
from lairs._codegen.schema_to_spec import (
    FieldSpec,
    ModelSpec,
    VariantSpec,
    schema_to_specs,
)

__all__ = [
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
]
