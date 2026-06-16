"""Vendoring manifest model and loader.

``lairs/lexicons/MANIFEST.toml`` records the provenance of the vendored lexicon
tree: the upstream Layers revision, the vendoring date, and a content hash of
the tree. The runtime representation is a :class:`Manifest` didactic model; this
module loads the TOML form into that model. The ``lexicon_tree_hash`` is stamped
into every emitted module so a generated file records the lexicon revision it
came from.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    from pathlib import Path

    from lairs._types import JsonValue

__all__ = ["Manifest", "load_manifest"]


class Manifest(dx.Model):
    """Provenance of the vendored lexicon tree.

    Parameters
    ----------
    layers_git_sha : str
        The upstream Layers git revision the tree was vendored from.
    layers_version : str
        The upstream Layers release version.
    vendored_at : str
        The ISO date the tree was vendored.
    lexicon_tree_hash : str
        A content hash of the vendored lexicon tree, stamped into emitted
        modules so a generated file records its source revision.
    lexicon_files : int
        The number of vendored lexicon JSON files.
    record_types : int
        The number of record definitions across the tree.
    """

    layers_git_sha: str = dx.field(description="upstream Layers git revision")
    layers_version: str = dx.field(description="upstream Layers release version")
    vendored_at: str = dx.field(description="ISO date the tree was vendored")
    lexicon_tree_hash: str = dx.field(description="content hash of the lexicon tree")
    lexicon_files: int = dx.field(
        default=0,
        description="number of vendored lexicon JSON files",
    )
    record_types: int = dx.field(
        default=0,
        description="number of record definitions across the tree",
    )


def load_manifest(path: Path) -> Manifest:
    """Load a vendoring manifest from its TOML file.

    Parameters
    ----------
    path : pathlib.Path
        The path to ``MANIFEST.toml``.

    Returns
    -------
    lairs._codegen.manifest.Manifest
        The parsed manifest model.
    """
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    provenance = _section(document.get("provenance"))
    counts = _section(document.get("counts"))
    return Manifest(
        layers_git_sha=_string(provenance.get("layers_git_sha")),
        layers_version=_string(provenance.get("layers_version")),
        vendored_at=_string(provenance.get("vendored_at")),
        lexicon_tree_hash=_string(provenance.get("lexicon_tree_hash")),
        lexicon_files=_int(counts.get("lexicon_files")),
        record_types=_int(counts.get("record_types")),
    )


def _section(value: JsonValue) -> dict[str, JsonValue]:
    """Return a TOML table as a string-keyed mapping, or an empty mapping."""
    return value if isinstance(value, dict) else {}


def _string(value: JsonValue) -> str:
    """Return ``value`` as a string, or the empty string when absent."""
    return value if isinstance(value, str) else ""


def _int(value: JsonValue) -> int:
    """Return ``value`` as an int, or zero when absent."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
