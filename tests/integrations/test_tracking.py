"""Unit and integration tests for lairs.integrations.tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lairs.integrations import tracking

if TYPE_CHECKING:
    from pathlib import Path


def test_exports() -> None:
    assert set(tracking.__all__) == {"log_revision"}


def test_log_revision_is_a_stub(tmp_path: Path) -> None:
    dx = pytest.importorskip("didactic.api")
    repo = dx.Repository.init(tmp_path)
    with pytest.raises(NotImplementedError):
        tracking.log_revision(repo, "v1", backend="mlflow")


@pytest.mark.integration
def test_log_revision_live() -> None:
    pytest.importorskip("mlflow")
    pytest.skip("requires a Repository and tracking backend")
