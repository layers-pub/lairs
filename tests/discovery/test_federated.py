"""Unit tests for lairs.discovery.federated."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from lairs.atproto.pds import PdsClient
from lairs.discovery.federated import datasets_using_ontology, discover_datasets

if TYPE_CHECKING:
    from collections.abc import Callable

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
