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


def test_dataset_card_emits_yaml_front_matter_for_license_and_source() -> None:
    bundle = provenance_bundle(
        corpus_uri="at://did:plc:abc/pub.layers.corpus.corpus/x",
        license="CC-BY-4.0",
        name="Mirrored",
    )
    card = dataset_card(bundle)
    # the machine-readable header leads the card and carries the license.
    assert card.startswith("---\n")
    header, _, _ = card.partition("\n---\n")
    assert "license: CC-BY-4.0" in header
    assert "source_datasets:" in header
    assert "at://did:plc:abc/pub.layers.corpus.corpus/x" in header


def test_dataset_card_omits_front_matter_when_no_metadata() -> None:
    # a bundle with no license, corpus_uri, or tag emits no YAML header.
    card = dataset_card(ProvenanceBundle(name="Bare"))
    assert not card.startswith("---")


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


class _FakeHubDataset:
    """Stand-in for ``datasets.Dataset`` that records its push_to_hub call."""

    pushes: ClassVar[list[dict[str, object]]] = []

    def __init__(self, view: pa.Table) -> None:
        self._view = view

    def push_to_hub(
        self,
        repo_id: str,
        *,
        config_name: str = "default",
        split: str = "train",
        private: bool = False,
        token: str | None = None,
    ) -> None:
        """Record the push instead of contacting the Hub."""
        _FakeHubDataset.pushes.append(
            {
                "repo_id": repo_id,
                "config_name": config_name,
                "split": split,
                "private": private,
                "token": token,
            },
        )


class _FakeHfApi:
    """Stand-in for ``huggingface_hub.HfApi`` that records uploaded card bytes."""

    uploaded: ClassVar[list[tuple[str, bytes]]] = []
    tokens: ClassVar[list[str | None]] = []

    def __init__(self, *, token: str | None = None) -> None:
        _FakeHfApi.tokens.append(token)

    def upload_file(
        self,
        *,
        path_or_fileobj: bytes,
        path_in_repo: str,
        repo_id: str,
        repo_type: str,
    ) -> None:
        """Record the upload instead of contacting the Hub."""
        _ = (repo_id, repo_type)
        _FakeHfApi.uploaded.append((path_in_repo, path_or_fileobj))


def _install_fake_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake ``datasets``/``huggingface_hub`` modules and reset recorders."""
    _FakeHubDataset.pushes.clear()
    _FakeHfApi.uploaded.clear()
    _FakeHfApi.tokens.clear()
    fake_datasets = types.SimpleNamespace(Dataset=_FakeHubDataset)
    fake_hub = types.SimpleNamespace(
        HfApi=_FakeHfApi,
        hf_hub_url=lambda repo_id, path, repo_type=None: (
            f"https://hf/{repo_id}/{path}?type={repo_type}"
        ),
    )
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)


def _uploaded_readme() -> str:
    """Return the decoded README the fake api recorded for the latest push."""
    for path_in_repo, payload in _FakeHfApi.uploaded:
        if path_in_repo == "README.md":
            return payload.decode("utf-8")
    msg = "no README.md was uploaded"
    raise AssertionError(msg)


def test_push_to_hub_pushes_dataset_uploads_card_and_returns_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # inject fake datasets/huggingface_hub modules so the push orchestration runs
    # end-to-end without the Hub; a real push needs write credentials, so the
    # network round-trip is covered by the load cassette instead.
    pa = pytest.importorskip("pyarrow")
    _install_fake_hub(monkeypatch)
    table = pa.table({"id": [1, 2], "text": ["a", "b"]})
    url = hub.push_to_hub(table, "org/corpus", private=True)
    assert len(_FakeHubDataset.pushes) == 1
    push = _FakeHubDataset.pushes[0]
    assert push["repo_id"] == "org/corpus"
    assert push["private"] is True
    assert push["split"] == "train"
    assert push["config_name"] == "default"
    assert "README.md" in {path for path, _ in _FakeHfApi.uploaded}
    assert url == "https://hf/org/corpus/README.md?type=dataset"


def test_push_to_hub_uploads_card_carrying_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the uploaded card bytes must carry the supplied provenance, so a regression
    # uploading an empty or wrong card is caught.
    pa = pytest.importorskip("pyarrow")
    _install_fake_hub(monkeypatch)
    bundle = provenance_bundle(
        corpus_uri="at://did:plc:abc/pub.layers.corpus.corpus/x",
        revision="rev9",
        license="CC-BY-4.0",
        name="Provenanced Corpus",
    )
    table = pa.table({"id": [1]})
    hub.push_to_hub(table, "org/corpus", provenance=bundle)
    readme = _uploaded_readme()
    assert "Provenanced Corpus" in readme
    assert "at://did:plc:abc/pub.layers.corpus.corpus/x" in readme
    assert "rev9" in readme
    assert "CC-BY-4.0" in readme
    assert bundle.lexicon_manifest_hash is not None
    assert bundle.lexicon_manifest_hash in readme


def test_push_to_hub_default_bundle_card_has_manifest_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # with no explicit bundle, the card still records the vendored manifest.
    pa = pytest.importorskip("pyarrow")
    _install_fake_hub(monkeypatch)
    table = pa.table({"id": [1]})
    hub.push_to_hub(table, "org/corpus")
    readme = _uploaded_readme()
    manifest = hub._read_manifest()
    assert manifest["lexicon_tree_hash"] in readme
    assert manifest["layers_version"] in readme


def test_push_to_hub_forwards_token_split_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pa = pytest.importorskip("pyarrow")
    _install_fake_hub(monkeypatch)
    table = pa.table({"id": [1]})
    hub.push_to_hub(
        table,
        "org/corpus",
        token="hf_secret",
        split="validation",
        config_name="subsetA",
    )
    push = _FakeHubDataset.pushes[0]
    assert push["token"] == "hf_secret"
    assert push["split"] == "validation"
    assert push["config_name"] == "subsetA"
    # the api is constructed with the same token for the card upload.
    assert _FakeHfApi.tokens == ["hf_secret"]


def test_load_from_hub_without_split_returns_dataset_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # with no split, load_from_hub returns whatever datasets.load_dataset yields;
    # for a multi-split repository that is a DatasetDict. Build a real one in
    # memory and stub the loader, so the DatasetDict type contract is verified
    # deterministically. (A recorded HTTP cassette is unreliable here: the
    # huggingface_hub request set shifts with the free-threaded-only hf_xet
    # backend, swapping HEAD probes for body-carrying GET downloads across
    # machines and CI.)
    datasets = pytest.importorskip("datasets")
    expected = datasets.DatasetDict(
        {
            "train": datasets.Dataset.from_dict({"text": ["a", "b"]}),
            "test": datasets.Dataset.from_dict({"text": ["c"]}),
        },
    )
    monkeypatch.setattr(datasets, "load_dataset", lambda *_args, **_kwargs: expected)
    loaded = hub.load_from_hub("org/multi-split-corpus")
    assert isinstance(loaded, datasets.DatasetDict)
    assert set(loaded) == {"train", "test"}


class _FakeLoadModule:
    """Stand-in ``datasets`` module recording the load_dataset arguments."""

    calls: ClassVar[list[dict[str, object]]] = []

    @staticmethod
    def load_dataset(
        path: str,
        *,
        split: str | None = None,
        revision: str | None = None,
        token: str | None = None,
    ) -> str:
        """Record the load arguments and return a sentinel for the split."""
        _FakeLoadModule.calls.append(
            {
                "path": path,
                "split": split,
                "revision": revision,
                "token": token,
            },
        )
        return f"dataset:{split}" if split is not None else "dataset-dict"


def test_load_from_hub_forwards_split_revision_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the split/revision/token parameters reach datasets.load_dataset, so a
    # caller can request a single split as a concrete Dataset.
    _FakeLoadModule.calls.clear()
    monkeypatch.setitem(sys.modules, "datasets", _FakeLoadModule)
    result = hub.load_from_hub(
        "org/corpus",
        split="test",
        revision="main",
        token="hf_secret",
    )
    assert result == "dataset:test"
    assert _FakeLoadModule.calls == [
        {
            "path": "org/corpus",
            "split": "test",
            "revision": "main",
            "token": "hf_secret",
        },
    ]


def test_load_from_hub_without_split_passes_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeLoadModule.calls.clear()
    monkeypatch.setitem(sys.modules, "datasets", _FakeLoadModule)
    result = hub.load_from_hub("org/corpus")
    assert result == "dataset-dict"
    assert _FakeLoadModule.calls[0]["split"] is None
