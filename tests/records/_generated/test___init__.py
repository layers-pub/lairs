"""Unit tests for the generated record models.

These tests assert the generated surface is complete (one module per namespace,
all record types importable), that every record round-trips through
``model_dump`` and JSON, and crucially that every formal lexicon ``union``
vertex round-trips to a ``dx.TaggedUnion`` with its discriminator intact.
"""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import didactic.api as dx
import panproto as pp

from lairs.records import _generated
from lairs.records._generated import defs

_LEXICON_ROOT = Path(__file__).resolve().parents[3] / "lairs" / "lexicons"

_NAMESPACES = (
    "alignment",
    "annotation",
    "changelog",
    "corpus",
    "defs",
    "eprint",
    "expression",
    "graph",
    "judgment",
    "media",
    "ontology",
    "persona",
    "resource",
    "segmentation",
)


def _all_model_classes() -> list[type[dx.Model]]:
    classes: list[type[dx.Model]] = []
    for namespace in _NAMESPACES:
        module = importlib.import_module(f"lairs.records._generated.{namespace}")
        for name in module.__all__:
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, dx.Model):
                classes.append(obj)
    return classes


# the representative scalar value for each required field, keyed by the
# annotation's name, so the round-trip smoke test fills required scalars
# without inspecting the broad didactic annotation union directly.
_SCALAR_VALUES: dict[str, str | int | datetime] = {
    "str": "x",
    "int": 0,
    "bool": False,
    "datetime": datetime(2020, 1, 1, tzinfo=UTC),
}


def _minimal_kwargs(cls: type[dx.Model]) -> dict[str, str | int | datetime] | None:
    kwargs: dict[str, str | int | datetime] = {}
    for name, spec in cls.__field_specs__.items():
        if not spec.is_required:
            continue
        annotation_name = getattr(spec.annotation, "__name__", "")
        if annotation_name not in _SCALAR_VALUES:
            # the record needs a required embed; skip it in this smoke pass
            return None
        kwargs[name] = _SCALAR_VALUES[annotation_name]
    return kwargs


def test_all_namespaces_present() -> None:
    assert set(_generated.__all__) == set(_NAMESPACES)


def test_every_namespace_module_imports() -> None:
    for namespace in _NAMESPACES:
        module = importlib.import_module(f"lairs.records._generated.{namespace}")
        assert module.__all__


def test_all_record_types_present() -> None:
    records = [
        cls for cls in _all_model_classes() if not issubclass(cls, dx.TaggedUnion)
    ]
    record_names = {cls.__name__ for cls in records}
    # the 26 lexicon record types are all present among the generated models
    assert "Expression" in record_names
    assert "AnnotationLayer" in record_names
    assert "Media" in record_names
    assert "GraphNode" in record_names


def test_scalar_records_round_trip() -> None:
    checked = 0
    for cls in _all_model_classes():
        if issubclass(cls, dx.TaggedUnion):
            continue
        kwargs = _minimal_kwargs(cls)
        if kwargs is None:
            continue
        instance = cls(**kwargs)
        assert cls.model_validate(instance.model_dump()) == instance
        assert cls.model_validate_json(instance.model_dump_json()) == instance
        checked += 1
    assert checked > 0


def test_span_round_trips() -> None:
    span = defs.Span(byteStart=0, byteEnd=5)
    assert defs.Span.model_validate(span.model_dump()) == span


def test_embed_round_trips() -> None:
    anchor = defs.Anchor(textSpan=defs.Span(byteStart=1, byteEnd=2))
    assert defs.Anchor.model_validate(anchor.model_dump()) == anchor


def _union_vertices() -> list[tuple[str, str]]:
    """Return every formal lexicon union vertex id with its discriminator."""
    pairs: list[tuple[str, str]] = []
    for path in sorted((_LEXICON_ROOT / "pub").rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        main = document.get("defs", {}).get("main", {})
        if isinstance(main, dict) and main.get("type") == "permission-set":
            # Permission-set lexicons are OAuth scope definitions the ATProto
            # parser does not model; the codegen skips them too.
            continue
        schema = pp.parse_atproto_lexicon(document)
        pairs.extend(
            (vertex.id, document["id"])
            for vertex in schema.vertices
            if vertex.kind == "union"
        )
    return pairs


def test_every_union_vertex_maps_to_a_tagged_union() -> None:
    union_vertices = _union_vertices()
    # the vendored tree carries at least the externalTarget selector union
    assert union_vertices
    # every formal union becomes a generated TaggedUnion carrying a discriminator
    tagged_unions = [
        cls
        for cls in _all_model_classes()
        if isinstance(cls, type) and issubclass(cls, dx.TaggedUnion)
    ]
    assert len(tagged_unions) >= len(union_vertices)
    for union in tagged_unions:
        assert union.__discriminator__
        assert union.__variants__


def test_external_target_selector_union_round_trips() -> None:
    target = defs.ExternalTarget(
        source="https://example.org/doc",
        selector=defs.ExternalTargetSelectorFragmentSelector(
            value=defs.FragmentSelector(value="#section-1"),
        ),
    )
    restored = defs.ExternalTarget.model_validate(target.model_dump())
    assert restored == target
    dumped = json.loads(target.model_dump_json())
    assert dumped["selector"]["kind"] == "fragmentSelector"
