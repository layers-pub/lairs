"""Adapter registry for codecs, exporters, and knowledge bases.

The registry resolves named adapters from two sources: in-process registration
and Python entry points (so third parties can ship adapters as their own
distributions). Entry-point groups are ``lairs.codecs``, ``lairs.exporters``,
and ``lairs.knowledge_bases``.

The registry is generic over the adapter type it holds, so lookups return a
precisely typed adapter class rather than a widened type. Three typed default
registries, one per family, are exposed through the module-level helpers.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lairs.integrations.ports import Codec, Exporter, KnowledgeBase

__all__ = [
    "Registry",
    "UnknownAdapterError",
    "available",
    "get_codec",
    "get_exporter",
    "get_knowledge_base",
    "register_codec",
    "register_exporter",
    "register_knowledge_base",
]


class UnknownAdapterError(KeyError):
    """Raised when a requested adapter name is not registered.

    The error message lists the adapters available in the relevant registry so
    that callers can recover.
    """


class Registry[A]:
    """A registry of named adapter classes for a single family.

    Lookups consult in-process registrations first and fall back to
    entry-point discovery, which runs at most once per registry.

    Parameters
    ----------
    family : str
        A human-readable family name used in error messages.
    group : str or None, optional
        The entry-point group to discover adapters from. When ``None``, no
        entry-point discovery is attempted.
    """

    def __init__(self, family: str, group: str | None = None) -> None:
        self._family = family
        self._group = group
        self._adapters: dict[str, type[A]] = {}
        self._discovered = False

    def register(self, name: str, adapter: type[A]) -> None:
        """Register an adapter class under a name.

        Parameters
        ----------
        name : str
            The adapter name.
        adapter : type
            The adapter class.
        """
        self._adapters[name] = adapter

    def get(self, name: str) -> type[A]:
        """Retrieve an adapter class by name.

        If the name is not registered in process, entry points are discovered
        and consulted once.

        Parameters
        ----------
        name : str
            The adapter name.

        Returns
        -------
        type
            The registered adapter class.

        Raises
        ------
        UnknownAdapterError
            If no adapter is registered under ``name``.
        """
        if name not in self._adapters:
            self._discover()

        if name not in self._adapters:
            known = ", ".join(sorted(self._adapters)) or "(none)"
            msg = f"unknown {self._family} adapter {name!r}; available: {known}"
            raise UnknownAdapterError(msg)

        return self._adapters[name]

    def available(self) -> list[str]:
        """List the names available in this registry.

        Triggers entry-point discovery if it has not run yet.

        Returns
        -------
        list of str
            The sorted available adapter names.
        """
        self._discover()

        return sorted(self._adapters)

    def _discover(self) -> None:
        """Discover entry-point adapters, at most once per registry."""
        if self._discovered or self._group is None:
            return

        self._discovered = True
        for ep in entry_points(group=self._group):
            # in-process registrations take precedence over entry points.
            if ep.name not in self._adapters:
                self._adapters[ep.name] = ep.load()


# the module-level default registries, one per adapter family.
_CODECS: Registry[Codec] = Registry("codec", "lairs.codecs")
_EXPORTERS: Registry[Exporter] = Registry(
    "exporter",
    "lairs.exporters",
)
_KNOWLEDGE_BASES: Registry[KnowledgeBase] = Registry(
    "knowledge base",
    "lairs.knowledge_bases",
)


def register_codec(name: str, adapter: type[Codec]) -> None:
    """Register a codec class in the default registry.

    Parameters
    ----------
    name : str
        The codec name.
    adapter : type
        The codec class.
    """
    _CODECS.register(name, adapter)


def register_exporter(name: str, adapter: type[Exporter]) -> None:
    """Register an exporter class in the default registry.

    Parameters
    ----------
    name : str
        The exporter name.
    adapter : type
        The exporter class.
    """
    _EXPORTERS.register(name, adapter)


def register_knowledge_base(
    name: str,
    adapter: type[KnowledgeBase],
) -> None:
    """Register a knowledge-base class in the default registry.

    Parameters
    ----------
    name : str
        The knowledge-base name.
    adapter : type
        The knowledge-base class.
    """
    _KNOWLEDGE_BASES.register(name, adapter)


def get_codec(name: str) -> type[Codec]:
    """Retrieve a codec class from the default registry.

    Parameters
    ----------
    name : str
        The codec name.

    Returns
    -------
    type
        The registered codec class.

    Raises
    ------
    UnknownAdapterError
        If no codec is registered under ``name``.
    """
    return _CODECS.get(name)


def get_exporter(name: str) -> type[Exporter]:
    """Retrieve an exporter class from the default registry.

    Parameters
    ----------
    name : str
        The exporter name.

    Returns
    -------
    type
        The registered exporter class.

    Raises
    ------
    UnknownAdapterError
        If no exporter is registered under ``name``.
    """
    return _EXPORTERS.get(name)


def get_knowledge_base(name: str) -> type[KnowledgeBase]:
    """Retrieve a knowledge-base class from the default registry.

    Parameters
    ----------
    name : str
        The knowledge-base name.

    Returns
    -------
    type
        The registered knowledge-base class.

    Raises
    ------
    UnknownAdapterError
        If no knowledge base is registered under ``name``.
    """
    return _KNOWLEDGE_BASES.get(name)


def available(family: str) -> list[str]:
    """List the available adapter names in a family of the default registries.

    Parameters
    ----------
    family : str
        The adapter family (``codecs``, ``exporters``, ``knowledge_bases``).

    Returns
    -------
    list of str
        The sorted available adapter names.

    Raises
    ------
    KeyError
        If ``family`` is not a known family.
    """
    registries: dict[
        str, Registry[Codec] | Registry[Exporter] | Registry[KnowledgeBase]
    ] = {
        "codecs": _CODECS,
        "exporters": _EXPORTERS,
        "knowledge_bases": _KNOWLEDGE_BASES,
    }
    if family not in registries:
        known = ", ".join(sorted(registries))
        msg = f"unknown adapter family {family!r}; known families: {known}"
        raise KeyError(msg)

    return registries[family].available()
