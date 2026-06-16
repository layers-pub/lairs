"""Unit and integration tests for lairs.atproto.firehose."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lairs.atproto import firehose
from lairs.atproto.firehose import FirehoseEvent, RepoSubscriber

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


def test_exports() -> None:
    assert set(firehose.__all__) == {
        "FirehoseEvent",
        "RepoSubscriber",
        "subscribe_repos",
    }


def test_firehose_event_model_round_trips() -> None:
    event = FirehoseEvent(
        seq=7,
        repo="did:plc:abc",
        collection="pub.layers.expression.expression",
        rkey="rk",
        action="create",
        record={"text": "hi"},
    )
    dumped = event.model_dump()
    assert dumped["seq"] == 7
    assert dumped["action"] == "create"
    restored = FirehoseEvent.model_validate(dumped)
    assert restored.record == {"text": "hi"}


def test_repo_subscriber_is_runtime_checkable() -> None:
    class _Sub:
        def subscribe(
            self,
            *,
            nsids: Sequence[str] | None = None,
            cursor: int | None = None,
        ) -> Iterator[FirehoseEvent]:
            _ = (nsids, cursor)
            return iter(())

    assert isinstance(_Sub(), RepoSubscriber)


def test_subscribe_repos_is_deferred() -> None:
    with pytest.raises(NotImplementedError):
        # consuming the generator triggers the deferred body.
        list(firehose.subscribe_repos("wss://relay.example"))


@pytest.mark.integration
def test_subscribe_repos_live() -> None:
    # exercises a real firehose subscription when opted in; skips otherwise.
    try:
        list(firehose.subscribe_repos("wss://relay.example"))
    except NotImplementedError:
        pytest.skip("firehose consumer is deferred to M3")
