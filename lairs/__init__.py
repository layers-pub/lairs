"""lairs: a read/write dataset client for the Layers format.

lairs reads and writes ``pub.layers.*`` records over ATProto, validates them
against models generated from the Layers lexicons, and exposes them through a
``datasets``-like API with first-class tooling for audio, video, and neural
modalities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.data import Corpus, load_corpus
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
    "__version__",
    "codec",
    "exporter",
    "knowledge_base",
    "load_corpus",
]

__version__ = "0.0.0"


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
