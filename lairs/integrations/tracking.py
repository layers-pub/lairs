"""Experiment-tracking hooks.

Logs a Repository revision (not a copy) as an artifact with the provenance
bundle, so a logged run pins exact record CIDs. Backends are Weights & Biases
and MLflow. Requires the ``lairs[tracking]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import didactic.api as dx

__all__ = ["log_revision"]


def log_revision(repo: dx.Repository, revision: str, *, backend: str) -> str:
    """Log a Repository revision as a tracked artifact.

    Parameters
    ----------
    repo : didactic.Repository
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
    NotImplementedError
        Always, until the tracking hooks land.
    """
    raise NotImplementedError
