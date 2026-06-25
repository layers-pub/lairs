"""Unit tests for lairs._codegen.pipeline."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from lairs._codegen import pipeline

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import ModuleType

# the real vendored lexicon tree, used by the drift gate test
_LEXICON_ROOT = Path(__file__).resolve().parents[2] / "lairs" / "lexicons"
_GENERATED_ROOT = (
    Path(__file__).resolve().parents[2] / "lairs" / "records" / "_generated"
)

_MANIFEST = """\
[provenance]
layers_git_sha = ""
layers_version = "0.0.0"
vendored_at = "2026-01-01"
lexicon_tree_hash = "feedface"

[counts]
lexicon_files = 1
record_types = 1
"""

_DEMO_LEXICON: dict[str, object] = {
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
                    "createdAt": {"type": "string", "format": "datetime"},
                    "anchor": {"type": "ref", "ref": "#anchor"},
                },
            },
        },
        "anchor": {
            "type": "object",
            "required": ["x"],
            "properties": {"x": {"type": "integer", "minimum": 0}},
        },
    },
}


def _write_demo_tree(root: Path) -> None:
    layers = root / "pub" / "layers" / "demo"
    layers.mkdir(parents=True)
    (layers / "demo.json").write_text(json.dumps(_DEMO_LEXICON), encoding="utf-8")
    (root / "MANIFEST.toml").write_text(_MANIFEST, encoding="utf-8")


def _import_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_exports() -> None:
    assert set(pipeline.__all__) == {"check", "generate", "namespace_specs"}


def test_generate_writes_namespace_modules(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_demo_tree(lexicon_root)
    paths = pipeline.generate(lexicon_root, out_root)
    names = {path.name for path in paths}
    assert "demo.py" in names
    assert "__init__.py" in names
    assert (out_root / "demo.py").exists()


def test_generated_module_imports_and_round_trips(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_demo_tree(lexicon_root)
    pipeline.generate(lexicon_root, out_root)
    module = _import_module(out_root / "demo.py", "pipeline_demo_module")
    demo = module.Demo
    inner = module.Anchor(x=1)
    instance = demo(
        text="hi",
        createdAt=datetime(2020, 1, 1, tzinfo=UTC),
        anchor=inner,
    )
    assert demo.model_validate(instance.model_dump()) == instance


def test_check_true_after_generate(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_demo_tree(lexicon_root)
    pipeline.generate(lexicon_root, out_root)
    assert pipeline.check(lexicon_root, out_root) is True


def test_check_false_when_module_missing(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_demo_tree(lexicon_root)
    out_root.mkdir()
    assert pipeline.check(lexicon_root, out_root) is False


def test_check_false_when_module_drifts(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_demo_tree(lexicon_root)
    pipeline.generate(lexicon_root, out_root)
    (out_root / "demo.py").write_text("# stale\n", encoding="utf-8")
    assert pipeline.check(lexicon_root, out_root) is False


def test_namespace_specs_groups_by_namespace(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    _write_demo_tree(lexicon_root)
    grouped: Mapping[str, object] = pipeline.namespace_specs(lexicon_root)
    assert "demo" in grouped


def test_generate_prunes_orphan_modules(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_demo_tree(lexicon_root)
    pipeline.generate(lexicon_root, out_root)
    orphan = out_root / "stale.py"
    orphan.write_text("# left behind after a namespace was removed\n", encoding="utf-8")
    pipeline.generate(lexicon_root, out_root)
    assert not orphan.exists()
    assert (out_root / "demo.py").exists()


def test_check_false_when_committed_module_is_an_orphan(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_demo_tree(lexicon_root)
    pipeline.generate(lexicon_root, out_root)
    (out_root / "stale.py").write_text("# orphan\n", encoding="utf-8")
    assert pipeline.check(lexicon_root, out_root) is False


_DEFS_LEXICON: dict[str, object] = {
    "lexicon": 1,
    "id": "pub.layers.defs.defs",
    "defs": {
        "anchor": {
            "type": "object",
            "required": ["x"],
            "properties": {"x": {"type": "integer", "minimum": 0}},
        },
    },
}

_ANNOTATION_LEXICON: dict[str, object] = {
    "lexicon": 1,
    "id": "pub.layers.annotation.annotation",
    "defs": {
        "main": {
            "type": "record",
            "key": "tid",
            "record": {
                "type": "object",
                "required": ["anchor"],
                "properties": {
                    "anchor": {
                        "type": "ref",
                        "ref": "pub.layers.defs.defs#anchor",
                    },
                },
            },
        },
    },
}


def _write_two_namespace_tree(root: Path) -> None:
    base = root / "pub" / "layers"
    (base / "defs").mkdir(parents=True)
    (base / "annotation").mkdir(parents=True)
    (base / "defs" / "defs.json").write_text(
        json.dumps(_DEFS_LEXICON), encoding="utf-8"
    )
    (base / "annotation" / "annotation.json").write_text(
        json.dumps(_ANNOTATION_LEXICON), encoding="utf-8"
    )
    (root / "MANIFEST.toml").write_text(_MANIFEST, encoding="utf-8")


def test_cross_namespace_embed_injects_sibling_import(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "lexicons"
    out_root = tmp_path / "out"
    _write_two_namespace_tree(lexicon_root)
    pipeline.generate(lexicon_root, out_root)
    annotation_text = (out_root / "annotation.py").read_text(encoding="utf-8")
    assert "from lairs.records._generated.defs import Anchor" in annotation_text
    # the cross-namespace embed is a runtime name, so TC001 must be suppressed
    assert "TC001" in annotation_text


def test_committed_records_match_vendored_lexicons() -> None:
    # the lairs gen --check drift gate over the real vendored tree
    assert pipeline.check(_LEXICON_ROOT, _GENERATED_ROOT) is True
