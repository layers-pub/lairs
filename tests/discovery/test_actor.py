"""Unit and integration tests for lairs.discovery.actor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto.appview import AppviewClient
from lairs.atproto.identity import IdentityResolver
from lairs.atproto.pds import PdsClient
from lairs.discovery.actor import list_datasets, table_of_contents
from lairs.discovery.models import DatasetFilter

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import PdsServer

_ENDPOINT = "https://pds.example"
_DID = "did:plc:x"
_CORPUS_NSID = "pub.layers.corpus.corpus"
_CORPUS_URI = f"at://{_DID}/{_CORPUS_NSID}/a"
_CORPUS_VALUE = {
    "$type": _CORPUS_NSID,
    "name": "demo corpus",
    "createdAt": "2026-06-18T00:00:00Z",
    "domain": "biomedical",
    "language": "en",
}
_DID_DOC = {
    "id": _DID,
    "service": [
        {
            "id": "#atproto_pds",
            "type": "AtprotoPersonalDataServer",
            "serviceEndpoint": _ENDPOINT,
        },
    ],
}


def _pds(handler: Callable[[httpx.Request], httpx.Response]) -> PdsClient:
    return PdsClient(_ENDPOINT, httpx.Client(transport=httpx.MockTransport(handler)))


def _appview(handler: Callable[[httpx.Request], httpx.Response]) -> AppviewClient:
    return AppviewClient(
        _ENDPOINT, httpx.Client(transport=httpx.MockTransport(handler))
    )


def _corpus_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={"records": [{"uri": _CORPUS_URI, "cid": "bafy", "value": _CORPUS_VALUE}]},
    )


def test_list_datasets_pds_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.repo.listRecords"
        assert request.url.params["collection"] == _CORPUS_NSID
        return _corpus_page()

    with _pds(handler) as client:
        summaries = list_datasets(_DID, source="pds", pds_client=client)
    assert len(summaries) == 1
    assert summaries[0].name == "demo corpus"
    assert summaries[0].domain == "biomedical"
    assert summaries[0].source_endpoint is None  # injected did + client, unresolved


def test_list_datasets_appview_path_pushes_facets() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.corpus.listCorpora"
        seen["repo"] = request.url.params.get("repo")
        seen["domain"] = request.url.params.get("domain")
        return _corpus_page()

    with _appview(handler) as client:
        summaries = list_datasets(
            _DID,
            source="appview",
            appview_client=client,
            filters=DatasetFilter(domain="biomedical"),
        )
    assert seen == {"repo": _DID, "domain": "biomedical"}
    assert len(summaries) == 1


def test_list_datasets_auto_prefers_appview() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.corpus.listCorpora"
        return _corpus_page()

    with _appview(handler) as client:
        summaries = list_datasets(_DID, appview_client=client)
    assert len(summaries) == 1


def test_list_datasets_client_side_filter_excludes() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _corpus_page()

    with _pds(handler) as client:
        summaries = list_datasets(
            _DID,
            source="pds",
            pds_client=client,
            filters=DatasetFilter(domain="legal"),
        )
    assert summaries == ()


def test_list_datasets_unknown_source_raises() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        list_datasets(_DID, source="bogus")


def test_list_datasets_appview_requires_endpoint() -> None:
    with pytest.raises(ValueError, match="appview endpoint or client"):
        list_datasets(_DID, source="appview")


def test_list_datasets_resolves_handle() -> None:
    def resolver_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/atproto-did":
            return httpx.Response(200, text=_DID)
        return httpx.Response(200, json=_DID_DOC)

    resolver = IdentityResolver(
        httpx.Client(transport=httpx.MockTransport(resolver_handler)),
    )

    def pds_handler(_request: httpx.Request) -> httpx.Response:
        return _corpus_page()

    with _pds(pds_handler) as client, resolver:
        summaries = list_datasets(
            "alice.test",
            source="pds",
            resolver=resolver,
            pds_client=client,
        )
    assert len(summaries) == 1
    assert summaries[0].handle == "alice.test"


def test_table_of_contents_lists_collections() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.repo.describeRepo"
        return httpx.Response(
            200,
            json={
                "did": _DID,
                "handle": "alice.test",
                "handleIsCorrect": True,
                "collections": [_CORPUS_NSID, "app.bsky.feed.post"],
            },
        )

    with _pds(handler) as client:
        toc = table_of_contents(_DID, pds_client=client)
    assert toc.did == _DID
    assert toc.handle == "alice.test"
    assert {item.nsid for item in toc.collections} == {
        _CORPUS_NSID,
        "app.bsky.feed.post",
    }
    assert toc.dataset_collections == (_CORPUS_NSID,)
    corpus_col = next(item for item in toc.collections if item.nsid == _CORPUS_NSID)
    assert corpus_col.is_dataset_like is True
    assert corpus_col.count is None


def test_table_of_contents_counts_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/xrpc/com.atproto.repo.describeRepo":
            return httpx.Response(
                200,
                json={
                    "did": _DID,
                    "handle": "alice.test",
                    "handleIsCorrect": True,
                    "collections": [_CORPUS_NSID],
                },
            )
        return httpx.Response(
            200,
            json={
                "records": [
                    {"uri": f"at://{_DID}/{_CORPUS_NSID}/a", "cid": "c1", "value": {}},
                    {"uri": f"at://{_DID}/{_CORPUS_NSID}/b", "cid": "c2", "value": {}},
                ],
            },
        )

    with _pds(handler) as client:
        toc = table_of_contents(_DID, counts=True, pds_client=client)
    assert toc.collections[0].count == 2


def _seed_corpus(server: PdsServer, name: str) -> None:
    """Create one corpus record on the live PDS."""
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {server.access_jwt}"},
        json={
            "repo": server.did,
            "collection": _CORPUS_NSID,
            "record": {
                "$type": _CORPUS_NSID,
                "name": name,
                "createdAt": "2026-06-18T00:00:00Z",
                "domain": "biomedical",
            },
        },
        timeout=30.0,
    )
    response.raise_for_status()


@pytest.mark.integration
def test_table_of_contents_live(pds_server: PdsServer) -> None:
    _seed_corpus(pds_server, "toc live corpus")
    client = PdsClient(pds_server.endpoint)
    toc = table_of_contents(pds_server.did, source="pds", pds_client=client)
    nsids = {item.nsid for item in toc.collections}
    assert _CORPUS_NSID in nsids
    assert _CORPUS_NSID in toc.dataset_collections


@pytest.mark.integration
def test_list_datasets_pds_live(pds_server: PdsServer) -> None:
    _seed_corpus(pds_server, "list live corpus")
    client = PdsClient(pds_server.endpoint)
    summaries = list_datasets(pds_server.did, source="pds", pds_client=client)
    assert any(summary.name == "list live corpus" for summary in summaries)
