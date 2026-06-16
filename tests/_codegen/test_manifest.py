"""Unit tests for lairs._codegen.manifest."""

from __future__ import annotations

from pathlib import Path

from lairs._codegen import manifest
from lairs._codegen.manifest import Manifest, load_manifest

_VENDORED_MANIFEST = (
    Path(__file__).resolve().parents[2] / "lairs" / "lexicons" / "MANIFEST.toml"
)

_TOML = """\
[provenance]
layers_git_sha = "abc123"
layers_version = "1.2.3"
vendored_at = "2026-06-16"
lexicon_tree_hash = "feedface"

[counts]
lexicon_files = 7
record_types = 3
"""


def test_exports() -> None:
    assert set(manifest.__all__) == {"Manifest", "load_manifest"}


def test_load_manifest_reads_provenance(tmp_path: Path) -> None:
    path = tmp_path / "MANIFEST.toml"
    path.write_text(_TOML, encoding="utf-8")
    loaded = load_manifest(path)
    assert loaded.layers_git_sha == "abc123"
    assert loaded.layers_version == "1.2.3"
    assert loaded.vendored_at == "2026-06-16"
    assert loaded.lexicon_tree_hash == "feedface"
    assert loaded.lexicon_files == 7
    assert loaded.record_types == 3


def test_manifest_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "MANIFEST.toml"
    path.write_text(_TOML, encoding="utf-8")
    loaded = load_manifest(path)
    assert Manifest.model_validate(loaded.model_dump()) == loaded


def test_loads_the_vendored_manifest() -> None:
    loaded = load_manifest(_VENDORED_MANIFEST)
    assert loaded.lexicon_tree_hash
    assert loaded.record_types == 26
