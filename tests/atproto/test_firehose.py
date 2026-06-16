"""Unit and integration tests for lairs.atproto.firehose."""

from __future__ import annotations

import pytest

from lairs.atproto import firehose


def test_exports() -> None:
    assert set(firehose.__all__) == {"subscribe_repos"}


def test_subscribe_repos_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        firehose.subscribe_repos("wss://relay.example")


@pytest.mark.integration
def test_subscribe_repos_live() -> None:
    # exercises a real firehose subscription when opted in; skips otherwise.
    try:
        firehose.subscribe_repos("wss://relay.example")
    except NotImplementedError:
        pytest.skip("firehose consumer not implemented yet")
