"""Single and bulk publishing, and the local-VCS-to-PDS workflow.

Maps a Repository revision to the minimal ``applyWrites`` set, ordering writes
by cross-reference dependency, with idempotent retry and a per-record result
report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    import didactic.api as dx

    from lairs._types import JsonValue

__all__ = ["apply_writes", "publish", "pull"]


def apply_writes(
    repo: str,
    writes: Sequence[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """Apply a batch of writes to a repo, ordered by dependency.

    Parameters
    ----------
    repo : str
        The authenticated repository DID.
    writes : collections.abc.Sequence of dict
        The create, update, and delete operations to apply.

    Returns
    -------
    list of dict
        A per-record result set (created, updated, skipped, or failed).

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError


def publish(
    repo: dx.Repository,
    revision: str,
    *,
    to: str,
    dry_run: bool = False,
) -> list[dict[str, JsonValue]]:
    """Publish a Repository revision to a PDS as the minimal write set.

    Parameters
    ----------
    repo : didactic.Repository
        The local didactic Repository holding the revision.
    revision : str
        The revision (commit or tag) to publish.
    to : str
        The target repository DID.
    dry_run : bool, optional
        If ``True``, compute and return the plan without sending writes.

    Returns
    -------
    list of dict
        The planned or applied per-record results.

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError


def pull(did: str) -> dx.Repository:
    """Ingest a PDS account's Layers records into a Repository.

    Parameters
    ----------
    did : str
        The account DID to pull from.

    Returns
    -------
    didactic.Repository
        A didactic Repository populated from the PDS records.

    Raises
    ------
    NotImplementedError
        Always, until the authoring layer lands.
    """
    raise NotImplementedError
