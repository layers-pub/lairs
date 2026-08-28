"""Configured dataset sources: where the index looks for corpora.

A :class:`Source` is a named PDS or relay endpoint to crawl for datasets. The
firehose discovers corpora automatically, but a PDS that is deliberately off the
firehose (for example a small operator hosting many accounts) is invisible to it,
so such a source must be registered explicitly. lairs ships a built-in default
for the public Layers PDS, and a user can add or override sources in a
``sources.toml`` file under the XDG config directory.

The config is a list of ``[[source]]`` tables::

    [[source]]
    name = "my-pds"
    endpoint = "https://pds.example"
    kind = "pds"        # "pds" or "relay"; defaults to "pds"
    enabled = true      # defaults to true

A user entry whose ``name`` matches a built-in overrides that built-in's fields
(for example to disable it), so ``[[source]]`` with ``name = "layers-pub"`` and
``enabled = false`` turns the default off. A new name adds a source and must give
an ``endpoint``.

This module reads configuration only; it performs no network access.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from lairs._types import JsonValue

__all__ = [
    "Source",
    "UnknownSourceError",
    "default_source",
    "default_sources_path",
    "load_sources",
    "resolve_source",
]

_SOURCES_FILE_ENV = "LAIRS_SOURCES_FILE"
"""The environment variable that overrides the sources file location."""

_XDG_CONFIG_ENV = "XDG_CONFIG_HOME"
"""The environment variable for the XDG config base directory."""

_SOURCES_FILE = "sources.toml"
"""The sources file name under the lairs config directory."""

_KIND_PDS = "pds"
"""The source kind for a Personal Data Server crawled via ``listRepos``."""

_KIND_RELAY = "relay"
"""The source kind for a relay or firehose endpoint."""


class Source(dx.Model):
    """A named PDS or relay endpoint to crawl for datasets.

    Attributes
    ----------
    name : str
        The source's short, unique name (used to select it on the CLI).
    endpoint : str
        The base URL of the PDS or relay.
    kind : str
        ``pds`` (crawled via ``com.atproto.sync.listRepos``) or ``relay`` (a
        firehose endpoint). Defaults to ``pds``.
    enabled : bool
        Whether the source is crawled. Defaults to ``True``.
    builtin : bool
        Whether the source ships with lairs rather than being user-configured.
    """

    name: str = dx.field(description="the source's short, unique name")
    endpoint: str = dx.field(description="the base URL of the PDS or relay")
    kind: str = dx.field(
        default=_KIND_PDS,
        description="pds (listRepos crawl) or relay (firehose)",
        extras={"knownValues": (_KIND_PDS, _KIND_RELAY)},
    )
    enabled: bool = dx.field(
        default=True,
        description="whether the source is crawled",
    )
    builtin: bool = dx.field(
        default=False,
        description="whether the source ships with lairs",
    )


# the built-in default sources, listed first. none are on the firehose, so they
# are registered here to stay discoverable. layers-pub carries the Universal
# Dependencies, UniMorph, and Unified Verb Index datasets; decomp carries the
# Universal Decompositional Semantics datasets under their decomp.io handles;
# megaattitude carries the MegaAttitude datasets under their megaattitude.io
# handles. all three resolve to one PDS today, and the index dedups by dataset
# URI, so a crawl that visits every source stays idempotent.
_BUILTIN_SOURCES: tuple[Source, ...] = (
    Source(
        name="layers-pub",
        endpoint="https://repo.layers.pub",
        kind=_KIND_PDS,
        builtin=True,
    ),
    Source(
        name="decomp",
        endpoint="https://repo.decomp.io",
        kind=_KIND_PDS,
        builtin=True,
    ),
    Source(
        name="megaattitude",
        endpoint="https://repo.megaattitude.io",
        kind=_KIND_PDS,
        builtin=True,
    ),
)


class UnknownSourceError(LookupError):
    """Raised when a source name does not resolve to a configured source."""


def default_sources_path() -> Path:
    """Return the sources file path, honoring the override and XDG config dir.

    Returns
    -------
    pathlib.Path
        The path from ``LAIRS_SOURCES_FILE`` when set, otherwise
        ``$XDG_CONFIG_HOME/lairs/sources.toml`` (or ``~/.config`` when the XDG
        variable is unset).
    """
    override = os.environ.get(_SOURCES_FILE_ENV)
    if override:
        return Path(override)
    config_home = os.environ.get(_XDG_CONFIG_ENV)
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "lairs" / _SOURCES_FILE


def _read_user_entries(path: Path) -> list[dict[str, JsonValue]]:
    """Read the raw ``[[source]]`` tables from a sources file.

    Parameters
    ----------
    path : pathlib.Path
        The sources file to read.

    Returns
    -------
    list of dict
        One mapping per ``[[source]]`` table; an empty list when the file is
        absent or holds no source tables.
    """
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    entries = data.get("source")
    if not isinstance(entries, list):
        return []
    return [
        {str(key): value for key, value in entry.items()}
        for entry in entries
        if isinstance(entry, dict)
    ]


def _source_from_entry(
    name: str,
    entry: Mapping[str, JsonValue],
    existing: Source | None,
) -> Source | None:
    """Build a source from a config entry, merging onto a built-in when present.

    Parameters
    ----------
    name : str
        The entry's source name.
    entry : collections.abc.Mapping
        The raw config fields.
    existing : Source or None
        The built-in source with the same name, when the entry overrides one.

    Returns
    -------
    Source or None
        The resolved source, or ``None`` when a new source omits an endpoint.
    """
    endpoint = entry.get("endpoint")
    kind = entry.get("kind")
    enabled = entry.get("enabled")
    if existing is not None:
        return Source(
            name=existing.name,
            endpoint=endpoint if isinstance(endpoint, str) else existing.endpoint,
            kind=kind if isinstance(kind, str) else existing.kind,
            enabled=enabled if isinstance(enabled, bool) else existing.enabled,
            builtin=existing.builtin,
        )
    if not isinstance(endpoint, str) or not endpoint:
        return None
    return Source(
        name=name,
        endpoint=endpoint,
        kind=kind if isinstance(kind, str) else _KIND_PDS,
        enabled=enabled if isinstance(enabled, bool) else True,
        builtin=False,
    )


def _merge(
    builtins: Sequence[Source],
    entries: Sequence[Mapping[str, JsonValue]],
) -> list[Source]:
    """Merge built-in sources with user config entries.

    Built-ins come first and keep their order; a user entry with a built-in's
    name overrides that built-in's fields, and a new name is appended.

    Parameters
    ----------
    builtins : collections.abc.Sequence of Source
        The built-in default sources.
    entries : collections.abc.Sequence of collections.abc.Mapping
        The raw user config entries.

    Returns
    -------
    list of Source
        The merged source list.
    """
    by_name: dict[str, Source] = {source.name: source for source in builtins}
    order: list[str] = [source.name for source in builtins]
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        merged = _source_from_entry(name, entry, by_name.get(name))
        if merged is None:
            continue
        if name not in by_name:
            order.append(name)
        by_name[name] = merged
    return [by_name[name] for name in order]


def load_sources(path: Path | None = None) -> list[Source]:
    """Load the configured sources, merging built-in defaults with the config.

    Parameters
    ----------
    path : pathlib.Path or None, optional
        The sources file to read; defaults to :func:`default_sources_path`.

    Returns
    -------
    list of Source
        The built-in sources merged with the user's ``sources.toml`` entries,
        built-ins first.
    """
    resolved = path if path is not None else default_sources_path()
    return _merge(_BUILTIN_SOURCES, _read_user_entries(resolved))


def default_source(path: Path | None = None) -> Source | None:
    """Return the source to crawl when the caller names none.

    This is the first enabled source in :func:`load_sources` order, which is the
    built-in Layers PDS on a default install. A user who disables or re-points
    the built-in in ``sources.toml`` therefore moves the default with it.

    Parameters
    ----------
    path : pathlib.Path or None, optional
        The sources file to read; defaults to :func:`default_sources_path`.

    Returns
    -------
    Source or None
        The first enabled source, or ``None`` when every source is disabled.
    """
    for source in load_sources(path):
        if source.enabled:
            return source
    return None


def resolve_source(name: str, *, path: Path | None = None) -> Source:
    """Resolve a source name to its configured source.

    Parameters
    ----------
    name : str
        The source name to resolve.
    path : pathlib.Path or None, optional
        The sources file to read; defaults to :func:`default_sources_path`.

    Returns
    -------
    Source
        The matching source.

    Raises
    ------
    UnknownSourceError
        When no configured source has the given name.
    """
    sources = load_sources(path)
    for source in sources:
        if source.name == name:
            return source
    known = ", ".join(sorted(source.name for source in sources)) or "(none)"
    msg = f"unknown source {name!r}; known sources: {known}"
    raise UnknownSourceError(msg)
