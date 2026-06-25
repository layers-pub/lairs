"""Unit tests for lairs.discovery.federated."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import httpx

from lairs.atproto.identity import IdentityResolution, IdentityResolver
from lairs.atproto.pds import PdsClient
from lairs.discovery import federated
from lairs.discovery.federated import datasets_using_ontology, discover_datasets

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import pytest

_ENDPOINT = "https://pds.example"
_CORPUS_NSID = "pub.layers.corpus.corpus"
_ONTOLOGY = "at://did:plc:o/pub.layers.ontology.ontology/x"


def _pds(handler: Callable[[httpx.Request], httpx.Response]) -> PdsClient:
    return PdsClient(_ENDPOINT, httpx.Client(transport=httpx.MockTransport(handler)))


def _corpus_record(repo: str, *, with_ontology: bool) -> httpx.Response:
    record: dict[str, object] = {
        "$type": _CORPUS_NSID,
        "name": f"corpus {repo}",
        "createdAt": "2026-06-18T00:00:00Z",
    }
    if with_ontology:
        record["ontologyRefs"] = [_ONTOLOGY]
    return httpx.Response(
        200,
        json={
            "records": [
                {
                    "uri": f"at://{repo}/{_CORPUS_NSID}/a",
                    "cid": "bafy",
                    "value": record,
                },
            ],
        },
    )


def _by_repo_handler(request: httpx.Request) -> httpx.Response:
    repo = request.url.params["repo"]
    if repo == "did:plc:bad":
        return httpx.Response(500)
    return _corpus_record(repo, with_ontology=repo == "did:plc:a")


def test_discover_datasets_merges_across_actors() -> None:
    with _pds(_by_repo_handler) as client:
        rows = discover_datasets(
            ["did:plc:a", "did:plc:b"],
            source="pds",
            pds_client=client,
        )
    assert {row.uri for row in rows} == {
        f"at://did:plc:a/{_CORPUS_NSID}/a",
        f"at://did:plc:b/{_CORPUS_NSID}/a",
    }


def test_discover_datasets_dedups_by_uri() -> None:
    with _pds(_by_repo_handler) as client:
        rows = discover_datasets(
            ["did:plc:a", "did:plc:a"],
            source="pds",
            pds_client=client,
        )
    assert len(rows) == 1


def test_discover_datasets_isolates_failures() -> None:
    with _pds(_by_repo_handler) as client:
        rows = discover_datasets(
            ["did:plc:bad", "did:plc:a"],
            source="pds",
            pds_client=client,
        )
    assert {row.uri for row in rows} == {f"at://did:plc:a/{_CORPUS_NSID}/a"}


def test_datasets_using_ontology_filters_by_ref() -> None:
    with _pds(_by_repo_handler) as client:
        rows = datasets_using_ontology(
            _ONTOLOGY,
            ["did:plc:a", "did:plc:b"],
            source="pds",
            pds_client=client,
        )
    # only did:plc:a's corpus references the ontology.
    assert {row.uri for row in rows} == {f"at://did:plc:a/{_CORPUS_NSID}/a"}


class _CountingResolver(IdentityResolver):
    """A fake resolver that records construction and per-actor resolution."""

    instances = 0

    def __init__(self) -> None:
        type(self).instances += 1
        self.resolved: list[str] = []
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.closed = True

    def resolve(self, actor: str) -> IdentityResolution:
        self.resolved.append(actor)
        did = "did:plc:" + actor.split(".", 1)[0]
        return IdentityResolution(did=did, pds_endpoint=_ENDPOINT, handle=actor)


def test_discover_datasets_shares_one_resolver_for_handle_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CountingResolver.instances = 0
    created: list[_CountingResolver] = []

    def factory() -> _CountingResolver:
        resolver = _CountingResolver()
        created.append(resolver)
        return resolver

    monkeypatch.setattr(federated, "IdentityResolver", factory)
    with _pds(_by_repo_handler) as client:
        rows = discover_datasets(
            ["a.test", "b.test"],
            source="pds",
            pds_client=client,
        )
    # one resolver is constructed for the whole seed and resolves both actors,
    # then is closed; the default path no longer builds a throwaway per actor.
    assert _CountingResolver.instances == 1
    assert created[0].resolved == ["a.test", "b.test"]
    assert created[0].closed is True
    assert {row.uri for row in rows} == {
        f"at://did:plc:a/{_CORPUS_NSID}/a",
        f"at://did:plc:b/{_CORPUS_NSID}/a",
    }


def test_discover_datasets_reuses_injected_resolver_without_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CountingResolver.instances = 0

    def factory() -> _CountingResolver:
        msg = "default resolver must not be constructed when one is injected"
        raise AssertionError(msg)

    monkeypatch.setattr(federated, "IdentityResolver", factory)
    injected = _CountingResolver()
    with _pds(_by_repo_handler) as client:
        discover_datasets(
            ["a.test"],
            source="pds",
            resolver=injected,
            pds_client=client,
        )
    # an injected resolver is reused as is and is NOT closed by the sweep.
    assert injected.resolved == ["a.test"]
    assert injected.closed is False
