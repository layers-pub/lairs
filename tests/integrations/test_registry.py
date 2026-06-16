"""Unit tests for lairs.integrations.registry."""

from __future__ import annotations

import pytest

from lairs.integrations import registry
from lairs.integrations.registry import Registry, UnknownAdapterError


class Widget:
    """A trivial concrete adapter type used to parametrize the registry."""

    name = "w"


def test_exports() -> None:
    assert set(registry.__all__) == {
        "Registry",
        "UnknownAdapterError",
        "available",
        "get_codec",
        "get_exporter",
        "get_knowledge_base",
        "register_codec",
        "register_exporter",
        "register_knowledge_base",
    }


def test_register_and_get() -> None:
    reg: Registry[Widget] = Registry("widget")
    reg.register("w", Widget)
    assert reg.get("w") is Widget
    assert reg.available() == ["w"]


def test_unknown_adapter_lists_available() -> None:
    reg: Registry[Widget] = Registry("widget")
    reg.register("w", Widget)
    with pytest.raises(UnknownAdapterError) as excinfo:
        reg.get("missing")
    assert "w" in str(excinfo.value)
    assert "widget" in str(excinfo.value)


def test_unknown_adapter_when_empty() -> None:
    reg: Registry[Widget] = Registry("widget")
    with pytest.raises(UnknownAdapterError) as excinfo:
        reg.get("missing")
    assert "(none)" in str(excinfo.value)


def test_entry_point_discovery_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeEntryPoint:
        name = "ep"

        def load(self) -> type[Widget]:
            return Widget

    def fake_entry_points(*, group: str) -> list[FakeEntryPoint]:
        calls.append(group)
        return [FakeEntryPoint()]

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)

    reg: Registry[Widget] = Registry("widget", group="lairs.widgets")
    assert reg.get("ep") is Widget
    # second lookup must not re-run discovery.
    reg.available()
    assert calls == ["lairs.widgets"]


def test_in_process_registration_beats_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FromEntryPoint:
        name = "x"

    class FromCode:
        name = "x"

    class FakeEntryPoint:
        name = "x"

        def load(self) -> type[FromEntryPoint]:
            return FromEntryPoint

    def fake_entry_points(*, group: str) -> list[FakeEntryPoint]:
        del group
        return [FakeEntryPoint()]

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)

    reg: Registry[FromCode] = Registry("widget", group="lairs.widgets")
    reg.register("x", FromCode)
    assert reg.get("x") is FromCode


def test_default_helpers_unknown() -> None:
    with pytest.raises(UnknownAdapterError):
        registry.get_codec("definitely-not-registered-xyz")
    with pytest.raises(UnknownAdapterError):
        registry.get_exporter("definitely-not-registered-xyz")
    with pytest.raises(UnknownAdapterError):
        registry.get_knowledge_base("definitely-not-registered-xyz")


def test_available_families() -> None:
    for family in ("codecs", "exporters", "knowledge_bases"):
        assert isinstance(registry.available(family), list)
    with pytest.raises(KeyError):
        registry.available("nonsense")


def test_register_default_codec() -> None:
    class MyCodec:
        name = "my"

    registry.register_codec("my-test-codec", MyCodec)
    assert registry.get_codec("my-test-codec") is MyCodec
