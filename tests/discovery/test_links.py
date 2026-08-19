"""Unit tests for lairs.discovery.links."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto.appview import AppviewClient
from lairs.discovery.links import (
    containers_of,
    datasets_for_eprint,
    members_of_collection,
    members_of_corpus,
    rollup_of_collection,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from lairs._types import JsonValue

_ENDPOINT = "https://appview.example"
_CORPUS = "at://did:plc:x/pub.layers.corpus.corpus/c"
_EPRINT = "at://did:plc:x/pub.layers.eprint.eprint/e"
_COLLECTION = "at://did:plc:x/pub.layers.catalog.collection/c"
_TREEBANK = "at://did:plc:ud/pub.layers.corpus.corpus/ewt"


def _appview(handler: Callable[[httpx.Request], httpx.Response]) -> AppviewClient:
    return AppviewClient(
        _ENDPOINT, httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_members_of_corpus_decodes_and_pushes_params() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.corpus.listMemberships"
        seen["corpusRef"] = request.url.params.get("corpusRef")
        seen["split"] = request.url.params.get("split")
        return httpx.Response(
            200,
            json={
                "records": [
                    {
                        "uri": "at://did:plc:y/pub.layers.corpus.membership/m",
                        "cid": "bafy",
                        "value": {
                            "$type": "pub.layers.corpus.membership",
                            "corpusRef": _CORPUS,
                            "expressionRef": "at://did:plc:y/pub.layers.expression.expression/e",
                            "createdAt": "2026-06-18T00:00:00Z",
                            "split": "train",
                        },
                    },
                ],
            },
        )

    with _appview(handler) as client:
        members = members_of_corpus(_CORPUS, appview_client=client, split="train")
    assert seen == {"corpusRef": _CORPUS, "split": "train"}
    assert len(members) == 1
    assert members[0].corpusRef == _CORPUS
    assert members[0].split == "train"


def test_members_of_corpus_requires_appview() -> None:
    with pytest.raises(ValueError, match="appview endpoint or client"):
        members_of_corpus(_CORPUS)


def test_datasets_for_eprint_decodes_and_pushes_params() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.eprint.listDataLinks"
        seen["eprintUri"] = request.url.params.get("eprintUri")
        seen["dataKind"] = request.url.params.get("dataKind")
        return httpx.Response(
            200,
            json={
                "records": [
                    {
                        "uri": "at://did:plc:y/pub.layers.eprint.dataLink/d",
                        "cid": "bafy",
                        "value": {
                            "$type": "pub.layers.eprint.dataLink",
                            "eprintUri": _EPRINT,
                            "dataKind": "corpus",
                            "corpusRef": _CORPUS,
                            "createdAt": "2026-06-18T00:00:00Z",
                        },
                    },
                ],
            },
        )

    with _appview(handler) as client:
        links = datasets_for_eprint(_EPRINT, appview_client=client, data_kind="corpus")
    assert seen == {"eprintUri": _EPRINT, "dataKind": "corpus"}
    assert len(links) == 1
    assert links[0].eprintUri == _EPRINT
    assert links[0].corpusRef == _CORPUS


def test_datasets_for_eprint_requires_appview() -> None:
    with pytest.raises(ValueError, match="appview endpoint or client"):
        datasets_for_eprint(_EPRINT)


def _membership_value(
    *,
    role: str,
    member_type: str,
    member_ref: str,
) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {
        "$type": "pub.layers.catalog.membership",
        "catalogRef": _COLLECTION,
        "createdAt": "2026-06-18T00:00:00Z",
        "role": role,
        "member": {
            "ref": {"recordRef": member_ref},
            "memberType": member_type,
        },
    }
    return value


def test_members_of_collection_decodes_and_pushes_params() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.catalog.listMembers"
        seen["collection"] = request.url.params.get("collection")
        seen["role"] = request.url.params.get("role")
        seen["memberType"] = request.url.params.get("memberType")
        return httpx.Response(
            200,
            json={
                "records": [
                    {
                        "uri": "at://did:plc:x/pub.layers.catalog.membership/m",
                        "cid": "bafy",
                        "value": _membership_value(
                            role="produce",
                            member_type="pub.layers.corpus.corpus",
                            member_ref=_TREEBANK,
                        ),
                    },
                ],
            },
        )

    with _appview(handler) as client:
        members = members_of_collection(
            _COLLECTION,
            appview_client=client,
            role="produce",
            member_type="pub.layers.corpus.corpus",
        )
    assert seen == {
        "collection": _COLLECTION,
        "role": "produce",
        "memberType": "pub.layers.corpus.corpus",
    }
    assert len(members) == 1
    assert members[0].role == "produce"
    assert members[0].member.ref.recordRef == _TREEBANK


def test_members_of_collection_requires_appview() -> None:
    with pytest.raises(ValueError, match="appview endpoint or client"):
        members_of_collection(_COLLECTION)


def test_containers_of_decodes_reverse_index() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.catalog.listContainers"
        seen["member"] = request.url.params.get("member")
        return httpx.Response(
            200,
            json={
                "records": [
                    {
                        "uri": "at://did:plc:pb/pub.layers.catalog.membership/a",
                        "cid": "bafy",
                        "value": _membership_value(
                            role="annotates",
                            member_type="pub.layers.corpus.corpus",
                            member_ref=_TREEBANK,
                        ),
                    },
                ],
            },
        )

    with _appview(handler) as client:
        containers = containers_of(_TREEBANK, appview_client=client)
    assert seen == {"member": _TREEBANK}
    assert len(containers) == 1
    assert containers[0].role == "annotates"


def test_rollup_of_collection_parses_totals_and_facets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.catalog.getRollup"
        assert request.url.params.get("collection") == _COLLECTION
        assert request.url.params.get("maxDepth") == "2"
        return httpx.Response(
            200,
            json={
                "collection": _COLLECTION,
                "computedAt": "2026-06-18T00:00:00Z",
                "descendantCollectionCount": 4,
                "totals": [
                    {
                        "produceCollection": "pub.layers.expression.expression",
                        "count": 16622,
                        "countSource": "computed",
                        "unit": "expression",
                    },
                ],
                "facets": [
                    {
                        "dimension": "language",
                        "values": [
                            {"value": "en", "count": 3, "valueUri": None},
                            {"value": "de", "count": 1},
                        ],
                    },
                ],
                "warnings": [
                    {"code": "count-declared-only", "subjectRef": _TREEBANK},
                ],
            },
        )

    with _appview(handler) as client:
        rollup = rollup_of_collection(
            _COLLECTION,
            appview_client=client,
            max_depth=2,
        )
    assert rollup.collection == _COLLECTION
    assert rollup.descendant_collection_count == 4
    assert len(rollup.totals) == 1
    assert rollup.totals[0].count == 16622
    assert rollup.totals[0].countSource == "computed"
    assert len(rollup.facets) == 1
    assert rollup.facets[0].dimension == "language"
    assert {v.value: v.count for v in rollup.facets[0].values} == {"en": 3, "de": 1}
    assert len(rollup.warnings) == 1
    assert rollup.warnings[0].code == "count-declared-only"


def test_rollup_of_collection_requires_appview() -> None:
    with pytest.raises(ValueError, match="appview endpoint or client"):
        rollup_of_collection(_COLLECTION)
