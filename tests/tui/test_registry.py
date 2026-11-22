"""Tests for the TUI's complete generated-record registry."""

from __future__ import annotations

import json
from pathlib import Path

import didactic.api as dx

from lairs.tui import registry


def test_registry_matches_every_vendored_record_model() -> None:
    root = Path(registry.__file__).parents[1] / "lexicons"
    expected: dict[str, tuple[str, str]] = {}
    for path in root.rglob("*.json"):
        lexicon = json.loads(path.read_text())
        if lexicon.get("defs", {}).get("main", {}).get("type") != "record":
            continue
        nsid = lexicon["id"]
        namespace, name = nsid.rsplit(".", 1)
        expected[nsid] = (namespace.rsplit(".", 1)[-1], name[0].upper() + name[1:])
    assert set(expected) == set(registry.RECORD_MODELS)
    for nsid, (namespace, name) in expected.items():
        model = registry.RECORD_MODELS[nsid]
        assert issubclass(model, dx.Model)
        assert model.__name__ == name
        assert model.__module__ == f"lairs.records._generated.{namespace}"
