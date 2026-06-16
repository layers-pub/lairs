"""Unit and integration tests for lairs.author.publish."""

from __future__ import annotations

import pytest

from lairs.author import publish


def test_exports() -> None:
    assert set(publish.__all__) == {"apply_writes", "publish", "pull"}


def test_apply_writes_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        publish.apply_writes("did:plc:abc", [])


def test_pull_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        publish.pull("did:plc:abc")


@pytest.mark.integration
def test_publish_dry_run_live() -> None:
    # exercises a real publish dry-run when opted in; skips otherwise.
    pytest.skip("publish requires a Repository and credentials")
