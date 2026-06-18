"""Unit and integration tests for lairs.integrations.hf.hub."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

import didactic.api as dx
import pytest

from lairs.integrations.hf import hub
from lairs.integrations.hf.hub import (
    ProvenanceBundle,
    dataset_card,
    provenance_bundle,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import ClassVar

    import pyarrow as pa


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


@pytest.fixture
def vcr_config() -> dict[str, list[str]]:
    """Strip credential headers from recorded hub cassettes."""
    return {"filter_headers": ["authorization", "cookie", "set-cookie"]}


class _FakeHubDataset:
    """Stand-in for ``datasets.Dataset`` that records its push_to_hub call."""

    pushes: ClassVar[list[tuple[str, bool]]] = []

    def __init__(self, view: pa.Table) -> None:
        self._view = view

    def push_to_hub(self, repo_id: str, *, private: bool = False) -> None:
        """Record the push instead of contacting the Hub."""
        _FakeHubDataset.pushes.append((repo_id, private))


class _FakeHfApi:
    """Stand-in for ``huggingface_hub.HfApi`` that records uploaded files."""

    uploaded: ClassVar[list[str]] = []

    def upload_file(
        self,
        *,
        path_or_fileobj: bytes,
        path_in_repo: str,
        repo_id: str,
        repo_type: str,
    ) -> None:
        """Record the upload instead of contacting the Hub."""
        _ = (path_or_fileobj, repo_id, repo_type)
        _FakeHfApi.uploaded.append(path_in_repo)


def test_push_to_hub_pushes_dataset_uploads_card_and_returns_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # inject fake datasets/huggingface_hub modules so the push orchestration runs
    # end-to-end without the Hub; a real push needs write credentials, so the
    # network round-trip is covered by the load cassette instead.
    pa = pytest.importorskip("pyarrow")
    _FakeHubDataset.pushes.clear()
    _FakeHfApi.uploaded.clear()
    fake_datasets = types.SimpleNamespace(Dataset=_FakeHubDataset)
    fake_hub = types.SimpleNamespace(
        HfApi=_FakeHfApi,
        hf_hub_url=lambda repo_id, path, repo_type=None: (
            f"https://hf/{repo_id}/{path}?type={repo_type}"
        ),
    )
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    table = pa.table({"id": [1, 2], "text": ["a", "b"]})
    url = hub.push_to_hub(table, "org/corpus", private=True)
    assert _FakeHubDataset.pushes == [("org/corpus", True)]
    assert "README.md" in _FakeHfApi.uploaded
    assert url == "https://hf/org/corpus/README.md?type=dataset"


@pytest.mark.vcr
def test_load_from_hub_reads_public_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # replay a recorded read of a tiny public dataset, so the datasets load path
    # runs deterministically offline from the committed cassette.
    pytest.importorskip("datasets")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    loaded = hub.load_from_hub("hf-internal-testing/fixtures_ade20k")
    assert len(loaded) >= 1
