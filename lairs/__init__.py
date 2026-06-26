"""lairs: a read/write dataset client for the Layers format.

lairs reads and writes ``pub.layers.*`` records over ATProto, validates them
against models generated from the Layers lexicons, and exposes them through a
``datasets``-like API with first-class tooling for audio, video, and neural
modalities.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from typing import TYPE_CHECKING

from lairs.atproto.auth import Session, authed_client, login
from lairs.data import Corpus, load_corpus
from lairs.discovery import (
    DatasetFilter,
    DatasetSummary,
    RepoTableOfContents,
    discover_datasets,
    list_datasets,
    table_of_contents,
)
from lairs.integrations.registry import (
    get_codec,
    get_exporter,
    get_knowledge_base,
)
from lairs.records.blobref import BlobRef

if TYPE_CHECKING:
    from lairs.integrations.ports import Codec, Exporter, KnowledgeBase

__all__ = [
    "BlobRef",
    "Corpus",
    "DatasetFilter",
    "DatasetSummary",
    "RepoTableOfContents",
    "Session",
    "__version__",
    "authed_client",
    "codec",
    "discover_datasets",
    "exporter",
    "knowledge_base",
    "list_datasets",
    "load_corpus",
    "login",
    "table_of_contents",
]

_FALLBACK_VERSION = "0.3.0"
"""The version reported when no installed distribution metadata is available.

This literal is the single source of truth for source and editable trees where
``importlib.metadata`` cannot find an installed ``lairs`` distribution. It must
be kept in step with the ``version`` field in ``pyproject.toml``.
"""


def _resolve_version() -> str:
    """Return the installed distribution version, falling back to a literal.

    Returns
    -------
    str
        The version string from the installed ``lairs`` distribution metadata,
        or ``_FALLBACK_VERSION`` when the package is not installed (for example
        when running from a source checkout).
    """
    try:
        return _distribution_version("lairs")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _resolve_version()


def codec(name: str) -> type[Codec]:
    """Look up a registered codec adapter class by name.

    Parameters
    ----------
    name : str
        The codec name (for example ``"conllu"`` or ``"brat"``).

    Returns
    -------
    type
        The registered codec class.

    Raises
    ------
    lairs.integrations.registry.UnknownAdapterError
        If no codec is registered under ``name``.
    """
    return get_codec(name)


def exporter(name: str) -> type[Exporter]:
    """Look up a registered exporter adapter class by name.

    Parameters
    ----------
    name : str
        The exporter name (for example ``"hf"`` or ``"torch"``).

    Returns
    -------
    type
        The registered exporter class.

    Raises
    ------
    lairs.integrations.registry.UnknownAdapterError
        If no exporter is registered under ``name``.
    """
    return get_exporter(name)


def knowledge_base(name: str) -> type[KnowledgeBase]:
    """Look up a registered knowledge-base adapter class by name.

    Parameters
    ----------
    name : str
        The knowledge-base name (for example ``"wikidata"``).

    Returns
    -------
    type
        The registered knowledge-base class.

    Raises
    ------
    lairs.integrations.registry.UnknownAdapterError
        If no knowledge base is registered under ``name``.
    """
    return get_knowledge_base(name)
