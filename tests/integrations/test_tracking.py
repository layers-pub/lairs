"""Unit and integration tests for lairs.integrations.tracking."""

from __future__ import annotations

import json
import sys
import types
from typing import TYPE_CHECKING

import didactic.api as dx
import pytest

from lairs.integrations import tracking
from lairs.records._generated.expression import Expression

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


_SEED_EXPRESSION = {
    "id": "66666666-6666-6666-6666-666666666666",
    "text": "publish me",
    "kind": "sentence",
    "createdAt": "2026-06-16T00:00:00Z",
}


def _seed_revision(repo: dx.Repository, tmp_path: Path) -> str:
    """Stage one real generated record and commit it, returning the revision.

    A revision must resolve in the Repository for :func:`tracking.log_revision`
    to accept it, so the tests commit a real :class:`Expression` rather than a
    hand-built id.
    """
    repo.add(Expression)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(_SEED_EXPRESSION))
    repo.add_data(str(seed), key="at://seed/expression/rec1")
    return repo.commit("seed", author="lairs <lairs@layers.pub>")


class _FakeArtifact:
    """A stand-in for ``wandb.Artifact`` recording its construction metadata."""

    def __init__(self, name: str, *, type: str, metadata: dict[str, object]) -> None:  # noqa: A002
        self.name = name
        self.type = type
        self.metadata = metadata


class _FakeRun:
    """A stand-in for an active ``wandb`` run capturing logged artifacts."""

    def __init__(self) -> None:
        self.logged: list[_FakeArtifact] = []

    def log_artifact(self, artifact: _FakeArtifact) -> None:
        self.logged.append(artifact)


def _fake_wandb(run: _FakeRun | None) -> types.ModuleType:
    """Build a fake ``wandb`` module exposing ``run`` and ``Artifact``."""
    module = types.ModuleType("wandb")
    module.run = run  # ty: ignore[unresolved-attribute]
    module.Artifact = _FakeArtifact  # ty: ignore[unresolved-attribute]
    return module


class _FakeMlflow(types.ModuleType):
    """A stand-in for ``mlflow`` capturing logged params and tags."""

    def __init__(self) -> None:
        super().__init__("mlflow")
        self.params: dict[str, object] = {}
        self.tags: dict[str, str] = {}

    def log_params(self, params: dict[str, object]) -> None:
        self.params = params

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value


def test_exports() -> None:
    assert set(tracking.__all__) == {"log_revision", "ProvenanceBundle"}


def test_importing_tracking_does_not_import_backends(
    assert_lazy_import: Callable[..., None],
) -> None:
    # importing the module must not pull in the optional, heavy backends.
    assert_lazy_import("lairs.integrations.tracking", "wandb", "mlflow")


def test_unknown_backend_raises_value_error(tmp_path: Path) -> None:
    repo = dx.Repository.init(tmp_path)
    with pytest.raises(ValueError, match="unknown tracking backend"):
        tracking.log_revision(repo, "v1", backend="tensorboard")


def test_missing_backend_dependency_raises_import_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # simulate the optional 'mlflow' backend being absent (an import of a module
    # mapped to None fails) so the clear error path runs even though the dev
    # environment installs lairs[tracking]. the import gate runs before the
    # revision check, so an unseeded repo still surfaces the ImportError.
    monkeypatch.setitem(sys.modules, "mlflow", None)
    repo = dx.Repository.init(tmp_path)
    with pytest.raises(ImportError, match="lairs\\[tracking\\]"):
        tracking.log_revision(repo, "v1", backend="mlflow")


def test_unresolvable_revision_raises_value_error(tmp_path: Path) -> None:
    # a typo'd revision must fail loudly rather than pinning wrong provenance.
    repo = dx.Repository.init(tmp_path)
    _seed_revision(repo, tmp_path)
    with pytest.raises(ValueError, match="does not resolve to a commit"):
        tracking.log_revision(repo, "deadbeef", backend="wandb")


def test_provenance_bundle_pins_revision_and_manifest_hash(tmp_path: Path) -> None:
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


def test_log_revision_wandb_logs_artifact_to_active_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # with an active run the provenance is logged as an artifact carrying the
    # bundle metadata, and the returned id is 'lairs-revision:<rev>'.
    run = _FakeRun()
    monkeypatch.setitem(sys.modules, "wandb", _fake_wandb(run))
    repo = dx.Repository.init(tmp_path)
    revision = _seed_revision(repo, tmp_path)

    artifact_id = tracking.log_revision(repo, revision, backend="wandb")

    assert artifact_id == f"lairs-revision:{revision}"
    assert len(run.logged) == 1
    logged = run.logged[0]
    assert logged.name == "lairs-revision"
    assert logged.type == "dataset"
    assert logged.metadata["revision"] == revision
    assert logged.metadata["lexicon_tree_hash"] != ""


def test_log_revision_wandb_without_active_run_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # with no active run the artifact would never be persisted; rather than
    # returning a success-looking id and dropping the provenance, it raises.
    monkeypatch.setitem(sys.modules, "wandb", _fake_wandb(None))
    repo = dx.Repository.init(tmp_path)
    revision = _seed_revision(repo, tmp_path)

    with pytest.raises(RuntimeError, match="active wandb run"):
        tracking.log_revision(repo, revision, backend="wandb")


def test_log_revision_mlflow_logs_params_and_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the mlflow backend records the bundle as params and the revision as a tag,
    # returning the same 'lairs-revision:<rev>' identifier.
    fake = _FakeMlflow()
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    repo = dx.Repository.init(tmp_path)
    revision = _seed_revision(repo, tmp_path)

    artifact_id = tracking.log_revision(repo, revision, backend="mlflow")

    assert artifact_id == f"lairs-revision:{revision}"
    assert fake.params["revision"] == revision
    assert fake.params["lexicon_tree_hash"] != ""
    assert fake.tags["lairs-revision"] == revision


@pytest.mark.integration
def test_log_revision_live_mlflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("mlflow")
    import mlflow  # noqa: PLC0415

    # recent mlflow refuses a bare filesystem tracking store unless explicitly
    # opted in; the test only needs a throwaway local store, so allow it.
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    repo = dx.Repository.init(tmp_path)
    revision = _seed_revision(repo, tmp_path)
    mlflow.set_tracking_uri(f"file://{tmp_path / 'mlruns'}")
    with mlflow.start_run():
        artifact = tracking.log_revision(repo, revision, backend="mlflow")
    assert artifact == f"lairs-revision:{revision}"
