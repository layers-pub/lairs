"""Unit and integration tests for lairs.atproto.appview."""

from __future__ import annotations

import pytest

from lairs.atproto import appview


def test_exports() -> None:
    assert set(appview.__all__) == {"AppviewClient"}


def test_appview_client_constructs() -> None:
    client = appview.AppviewClient("https://appview.example")
    assert client.endpoint == "https://appview.example"


def test_query_is_a_stub() -> None:
    client = appview.AppviewClient("https://appview.example")
    with pytest.raises(NotImplementedError):
        client.query("corpus.listCorpora", {})


@pytest.mark.integration
def test_query_live() -> None:
    # exercises a real appview query when opted in; skips otherwise.
    client = appview.AppviewClient("https://appview.example")
    try:
        client.query("corpus.listCorpora", {})
    except NotImplementedError:
        pytest.skip("appview client not implemented yet")
