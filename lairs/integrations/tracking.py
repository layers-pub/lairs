"""Experiment-tracking hooks.

Logs a Repository revision (not a copy) as an artifact with the provenance
bundle, so a logged run pins exact record CIDs. Backends are Weights & Biases
and MLflow. Requires the ``lairs[tracking]`` extra at runtime.

Reproducibility comes from the revision id: a logged run records the exact
commit (or tag) and the vendored lexicon manifest hash that the records were
generated against, so the dataset behind a run can always be rebuilt. The
backend libraries are imported lazily inside :func:`log_revision`, so importing
this module never pulls in ``wandb`` or ``mlflow``.
"""

from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from lairs._types import JsonValue

__all__ = ["ProvenanceBundle", "log_revision"]

# the recognised tracking backends.
_BACKEND_WANDB = "wandb"
_BACKEND_MLFLOW = "mlflow"
_VALID_BACKENDS = frozenset({_BACKEND_WANDB, _BACKEND_MLFLOW})

# the vendored lexicon manifest, read for the provenance hash.
_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "lexicons" / "MANIFEST.toml"

# the artifact name a logged revision is recorded under.
_ARTIFACT_NAME = "lairs-revision"


class ProvenanceBundle(dx.Model):
    """The provenance pinned alongside a logged Repository revision.

    Attributes
    ----------
    revision : str
        The Repository revision (commit id or tag) the run was logged against.
    lexicon_tree_hash : str
        The content hash of the vendored lexicon tree the records were generated
        from, read from ``lairs/lexicons/MANIFEST.toml``.
    layers_version : str
        The upstream Layers release version the lexicons were vendored from.
    working_dir : str
        The Repository working directory the revision was read from.
    """

    revision: str = dx.field(description="Repository revision the run was logged for")
    lexicon_tree_hash: str = dx.field(
        default="",
        description="content hash of the vendored lexicon tree",
    )
    layers_version: str = dx.field(
        default="",
        description="upstream Layers release version",
    )
    working_dir: str = dx.field(
        default="",
        description="Repository working directory the revision came from",
    )


def _manifest_provenance() -> tuple[str, str]:
    """Return the lexicon tree hash and Layers version from the manifest.

    Returns
    -------
    tuple of (str, str)
        The ``lexicon_tree_hash`` and ``layers_version`` from the vendored
        manifest, each defaulting to the empty string when absent.
    """
    if not _MANIFEST_PATH.exists():
        return "", ""
    with _MANIFEST_PATH.open("rb") as handle:
        document = tomllib.load(handle)
    provenance = document.get("provenance")
    section: dict[str, JsonValue] = provenance if isinstance(provenance, dict) else {}
    tree_hash = section.get("lexicon_tree_hash")
    version = section.get("layers_version")
    return (
        tree_hash if isinstance(tree_hash, str) else "",
        version if isinstance(version, str) else "",
    )


def _build_bundle(repo: dx.Repository, revision: str) -> ProvenanceBundle:
    """Assemble the provenance bundle for a Repository revision.

    Parameters
    ----------
    repo : didactic.api.Repository
        The Repository holding the revision.
    revision : str
        The revision (commit or tag) to log.

    Returns
    -------
    ProvenanceBundle
        The provenance pinned alongside the logged revision.
    """
    tree_hash, version = _manifest_provenance()
    return ProvenanceBundle(
        revision=revision,
        lexicon_tree_hash=tree_hash,
        layers_version=version,
        working_dir=str(repo.working_dir),
    )


def _require(backend: str) -> None:
    """Raise a clear error when a backend's optional dependency is missing.

    Parameters
    ----------
    backend : str
        The tracking backend whose import to probe.

    Raises
    ------
    ImportError
        If the backend's package is not installed.
    """
    if importlib.util.find_spec(backend) is None:
        msg = (
            f"the {backend!r} backend needs the optional 'lairs[tracking]' extra; "
            f"install it with 'pip install lairs[tracking]'"
        )
        raise ImportError(msg)


def log_revision(repo: dx.Repository, revision: str, *, backend: str) -> str:
    """Log a Repository revision as a tracked artifact.

    The revision itself (not a copy of the data) is recorded together with a
    :class:`ProvenanceBundle`, so a logged run pins the exact commit and the
    vendored lexicon manifest hash that the records were generated against. The
    backend library is imported lazily, so a missing optional dependency raises a
    clear error only when that backend is used.

    Parameters
    ----------
    repo : didactic.api.Repository
        The Repository holding the revision.
    revision : str
        The revision (commit or tag) to log.
    backend : str
        The tracking backend (``"wandb"`` or ``"mlflow"``).

    Returns
    -------
    str
        The tracked artifact identifier.

    Raises
    ------
    ValueError
        If ``backend`` is not a recognised tracking backend.
    ImportError
        If the backend's optional dependency is not installed.
    """
    if backend not in _VALID_BACKENDS:
        valid = sorted(_VALID_BACKENDS)
        msg = f"unknown tracking backend {backend!r}; expected one of {valid}"
        raise ValueError(msg)
    _require(backend)
    bundle = _build_bundle(repo, revision)
    if backend == _BACKEND_WANDB:
        return _log_wandb(bundle)
    return _log_mlflow(bundle)


def _log_wandb(bundle: ProvenanceBundle) -> str:
    """Log a provenance bundle to Weights & Biases as an artifact.

    Parameters
    ----------
    bundle : ProvenanceBundle
        The provenance to record.

    Returns
    -------
    str
        The logged artifact name and revision, as ``"name:revision"``.
    """
    import wandb  # noqa: PLC0415

    metadata: dict[str, JsonValue] = json.loads(bundle.model_dump_json())
    artifact = wandb.Artifact(_ARTIFACT_NAME, type="dataset", metadata=metadata)
    run = wandb.run
    if run is not None:
        run.log_artifact(artifact)
    return f"{_ARTIFACT_NAME}:{bundle.revision}"


def _log_mlflow(bundle: ProvenanceBundle) -> str:
    """Log a provenance bundle to MLflow as run parameters and a tag.

    Parameters
    ----------
    bundle : ProvenanceBundle
        The provenance to record.

    Returns
    -------
    str
        The logged artifact name and revision, as ``"name:revision"``.
    """
    import mlflow  # noqa: PLC0415

    params: dict[str, JsonValue] = json.loads(bundle.model_dump_json())
    mlflow.log_params(params)
    mlflow.set_tag(_ARTIFACT_NAME, bundle.revision)
    return f"{_ARTIFACT_NAME}:{bundle.revision}"
