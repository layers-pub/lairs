"""Unit tests for lairs.discovery.links."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto.appview import AppviewClient
from lairs.discovery.links import datasets_for_eprint, members_of_corpus

if TYPE_CHECKING:
    from collections.abc import Callable

_ENDPOINT = "https://appview.example"
_CORPUS = "at://did:plc:x/pub.layers.corpus.corpus/c"
_EPRINT = "at://did:plc:x/pub.layers.eprint.eprint/e"


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
