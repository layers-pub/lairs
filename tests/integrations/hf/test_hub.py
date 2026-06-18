"""Unit and integration tests for lairs.integrations.hf.hub."""

from __future__ import annotations

import sys

import didactic.api as dx
import pytest

from lairs.integrations.hf import hub
from lairs.integrations.hf.hub import (
    ProvenanceBundle,
    dataset_card,
    provenance_bundle,
)


def test_exports() -> None:
    assert set(hub.__all__) == {
        "ProvenanceBundle",
        "dataset_card",
        "load_from_hub",
        "provenance_bundle",
        "push_to_hub",
    }


def test_provenance_bundle_is_a_model() -> None:
    bundle = ProvenanceBundle()
    assert isinstance(bundle, dx.Model)


def test_read_manifest_returns_hash_and_version() -> None:
    manifest = hub._read_manifest()
    assert isinstance(manifest["lexicon_tree_hash"], str)
    assert len(manifest["lexicon_tree_hash"]) > 0
    assert isinstance(manifest["layers_version"], str)


def test_provenance_bundle_fills_manifest_fields() -> None:
    bundle = provenance_bundle(
        corpus_uri="at://did:plc:abc/pub.layers.corpus.corpus/x",
        revision="rev1",
        tag="v0.1",
        license="CC-BY-4.0",
        name="My Corpus",
    )
    assert bundle.corpus_uri == "at://did:plc:abc/pub.layers.corpus.corpus/x"
    assert bundle.revision == "rev1"
    assert bundle.tag == "v0.1"
    assert bundle.license == "CC-BY-4.0"
    assert bundle.name == "My Corpus"
    # the lexicon manifest fields are filled from the vendored manifest.
    assert bundle.lexicon_manifest_hash is not None
    assert bundle.layers_version is not None


def test_dataset_card_includes_all_provenance() -> None:
    bundle = provenance_bundle(
        corpus_uri="at://did:plc:abc/pub.layers.corpus.corpus/x",
        revision="rev1",
        tag="v0.1",
        license="CC-BY-4.0",
        name="My Corpus",
    )
    card = dataset_card(bundle)
    assert "# My Corpus" in card
    assert "at://did:plc:abc/pub.layers.corpus.corpus/x" in card
    assert "rev1" in card
    assert "v0.1" in card
    assert "CC-BY-4.0" in card
    assert bundle.lexicon_manifest_hash is not None
    assert bundle.lexicon_manifest_hash in card
    assert bundle.layers_version is not None
    assert bundle.layers_version in card


def test_dataset_card_omits_unset_fields() -> None:
    bundle = ProvenanceBundle(name="Sparse")
    card = dataset_card(bundle)
    assert "# Sparse" in card
    assert "Corpus AT-URI" not in card
    assert "Repository revision" not in card
    assert "License" not in card


def test_dataset_card_default_heading() -> None:
    card = dataset_card(ProvenanceBundle())
    assert "# lairs corpus mirror" in card


def test_push_to_hub_without_datasets_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # simulate the optional 'datasets' library being absent so the clear error
    # path runs even though the dev environment installs lairs[hf].
    monkeypatch.setitem(sys.modules, "datasets", None)
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1]})
    with pytest.raises(ImportError, match="lairs\\[hf\\]"):
        hub.push_to_hub(table, "org/corpus")


def test_load_from_hub_without_datasets_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "datasets", None)
    with pytest.raises(ImportError, match="lairs\\[hf\\]"):
        hub.load_from_hub("org/corpus")


@pytest.mark.integration
def test_push_to_hub_live() -> None:
    pytest.importorskip("datasets")
    pytest.importorskip("huggingface_hub")
    pytest.skip("requires Hub credentials")


@pytest.mark.integration
def test_load_from_hub_live() -> None:
    pytest.importorskip("datasets")
    pytest.skip("requires a published Hub mirror")
