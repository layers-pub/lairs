"""Unit and integration tests for lairs.integrations.tracking."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from lairs.integrations import tracking

if TYPE_CHECKING:
    from pathlib import Path


def test_exports() -> None:
    assert set(tracking.__all__) == {"log_revision", "ProvenanceBundle"}


def test_importing_tracking_does_not_import_backends() -> None:
    # importing the module must not pull in the optional, heavy backends.
    assert "wandb" not in sys.modules
    assert "mlflow" not in sys.modules


def test_unknown_backend_raises_value_error(tmp_path: Path) -> None:
    dx = pytest.importorskip("didactic.api")
    repo = dx.Repository.init(tmp_path)
    with pytest.raises(ValueError, match="unknown tracking backend"):
        tracking.log_revision(repo, "v1", backend="tensorboard")


def test_missing_backend_dependency_raises_import_error(tmp_path: Path) -> None:
    dx = pytest.importorskip("didactic.api")
    repo = dx.Repository.init(tmp_path)
    if tracking.importlib.util.find_spec("mlflow") is not None:
        pytest.skip("mlflow is installed; cannot exercise the missing-dep path")
    with pytest.raises(ImportError, match="lairs\\[tracking\\]"):
        tracking.log_revision(repo, "v1", backend="mlflow")


def test_provenance_bundle_pins_revision_and_manifest_hash(tmp_path: Path) -> None:
    dx = pytest.importorskip("didactic.api")
    repo = dx.Repository.init(tmp_path)
    bundle = tracking._build_bundle(repo, "v7")
    assert bundle.revision == "v7"
    # the manifest hash is read from the vendored MANIFEST.toml and must be set.
    assert bundle.lexicon_tree_hash != ""
    assert bundle.layers_version != ""
    assert bundle.working_dir == str(repo.working_dir)


def test_manifest_provenance_reads_the_vendored_manifest() -> None:
    tree_hash, version = tracking._manifest_provenance()
    assert len(tree_hash) == 64  # a sha-256 hex digest
    assert version != ""


@pytest.mark.integration
def test_log_revision_live_mlflow(tmp_path: Path) -> None:
    pytest.importorskip("mlflow")
    pytest.importorskip("didactic.api")
    import didactic.api as dx  # noqa: PLC0415
    import mlflow  # noqa: PLC0415  # ty: ignore[unresolved-import]

    repo = dx.Repository.init(tmp_path)
    mlflow.set_tracking_uri(f"file://{tmp_path / 'mlruns'}")
    with mlflow.start_run():
        artifact = tracking.log_revision(repo, "v1", backend="mlflow")
    assert artifact == "lairs-revision:v1"
