"""Unit tests for lairs.discovery.sources."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lairs.discovery import sources

if TYPE_CHECKING:
    from pathlib import Path


def test_exports() -> None:
    assert set(sources.__all__) == {
        "Source",
        "UnknownSourceError",
        "default_source",
        "default_sources_path",
        "load_sources",
        "resolve_source",
    }


def test_default_sources_are_builtin(tmp_path: Path) -> None:
    # with no config file, only the built-in default is present.
    loaded = sources.load_sources(tmp_path / "absent.toml")
    assert [s.name for s in loaded] == ["layers-pub", "decomp", "megaattitude"]
    layers = loaded[0]
    assert layers.endpoint == "https://repo.layers.pub"
    assert layers.kind == "pds"
    assert layers.enabled is True
    assert layers.builtin is True


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_user_source_is_added(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "sources.toml",
        '[[source]]\nname = "my-pds"\nendpoint = "https://pds.example"\n',
    )
    loaded = sources.load_sources(cfg)
    names = [s.name for s in loaded]
    assert names == ["layers-pub", "decomp", "megaattitude", "my-pds"]
    added = loaded[-1]
    assert added.endpoint == "https://pds.example"
    assert added.kind == "pds"
    assert added.enabled is True
    assert added.builtin is False


def test_user_entry_overrides_builtin(tmp_path: Path) -> None:
    # a user entry with a built-in's name overrides its fields (here, disabling
    # it) while keeping it a built-in and its endpoint.
    cfg = _write(
        tmp_path / "sources.toml",
        '[[source]]\nname = "layers-pub"\nenabled = false\n',
    )
    layers = sources.resolve_source("layers-pub", path=cfg)
    assert layers.enabled is False
    assert layers.builtin is True
    assert layers.endpoint == "https://repo.layers.pub"


def test_new_source_without_endpoint_is_skipped(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "sources.toml", '[[source]]\nname = "broken"\n')
    assert [s.name for s in sources.load_sources(cfg)] == [
        "layers-pub",
        "decomp",
        "megaattitude",
    ]


def test_relay_kind_is_honored(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "sources.toml",
        '[[source]]\nname = "relay"\n'
        'endpoint = "wss://relay.example"\nkind = "relay"\n',
    )
    relay = sources.resolve_source("relay", path=cfg)
    assert relay.kind == "relay"
    assert relay.endpoint == "wss://relay.example"


def test_default_source_is_the_builtin(tmp_path: Path) -> None:
    # with no config file, the default target is the built-in Layers PDS.
    default = sources.default_source(tmp_path / "absent.toml")
    assert default is not None
    assert default.name == "layers-pub"
    assert default.endpoint == "https://repo.layers.pub"


def test_default_source_follows_a_repointed_builtin(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "sources.toml",
        '[[source]]\nname = "layers-pub"\nendpoint = "https://mirror.example"\n',
    )
    default = sources.default_source(cfg)
    assert default is not None
    assert default.endpoint == "https://mirror.example"


def test_default_source_skips_a_disabled_builtin(tmp_path: Path) -> None:
    # disabling the built-ins hands the default to the next enabled source.
    cfg = _write(
        tmp_path / "sources.toml",
        '[[source]]\nname = "layers-pub"\nenabled = false\n'
        '[[source]]\nname = "decomp"\nenabled = false\n'
        '[[source]]\nname = "megaattitude"\nenabled = false\n'
        '[[source]]\nname = "my-pds"\nendpoint = "https://pds.example"\n',
    )
    default = sources.default_source(cfg)
    assert default is not None
    assert default.name == "my-pds"


def test_default_source_is_none_when_all_disabled(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "sources.toml",
        '[[source]]\nname = "layers-pub"\nenabled = false\n'
        '[[source]]\nname = "decomp"\nenabled = false\n'
        '[[source]]\nname = "megaattitude"\nenabled = false\n',
    )
    assert sources.default_source(cfg) is None


def test_resolve_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(
        sources.UnknownSourceError,
        match="unknown source 'nope'",
    ) as excinfo:
        sources.resolve_source("nope", path=tmp_path / "absent.toml")
    # the error names the known sources to help the user.
    assert "layers-pub" in str(excinfo.value)


def test_default_path_honors_override_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("LAIRS_SOURCES_FILE", str(target))
    assert sources.default_sources_path() == target


def test_default_path_uses_xdg_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LAIRS_SOURCES_FILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert sources.default_sources_path() == tmp_path / "lairs" / "sources.toml"
