"""HuggingFace Hub push and pull.

Mirrors a corpus to the Hub as Arrow/Parquet shards with an auto-generated
dataset card carrying full provenance, and reads a mirror back. The Hub is an
export and mirror target; the PDS and the didactic Repository stay canonical, so
the card records exactly the references needed to reproduce the mirror from
source: the corpus AT-URI, the Repository revision or tag, the vendored lexicon
manifest hash, and the license from the ``corpus`` record.

``datasets`` and ``huggingface_hub`` are optional dependencies provided by the
``lairs[hf]`` extra. They are imported lazily inside the functions that need
them, so importing this module never pulls them in; the concrete return types are
bound only under ``TYPE_CHECKING``.
"""

from __future__ import annotations

import tomllib
from importlib.resources import files
from typing import TYPE_CHECKING

import didactic.api as dx

if TYPE_CHECKING:
    import pyarrow as pa
    from datasets import Dataset

__all__ = [
    "ProvenanceBundle",
    "dataset_card",
    "load_from_hub",
    "provenance_bundle",
    "push_to_hub",
]

# the manifest is a package resource so it is reachable from an installed wheel
# as well as from a source checkout.
_MANIFEST_PACKAGE = "lairs.lexicons"
_MANIFEST_NAME = "MANIFEST.toml"


class ProvenanceBundle(dx.Model):
    """The provenance carried on a mirrored corpus's dataset card.

    The bundle records everything needed to trace a Hub mirror back to its
    canonical sources. The PDS and the Repository remain the source of truth; the
    bundle pins the exact corpus AT-URI, the Repository revision or tag, the
    vendored lexicon manifest hash, and the corpus license.

    Attributes
    ----------
    corpus_uri : str or None, optional
        The AT-URI of the source ``corpus`` record.
    revision : str or None, optional
        The didactic Repository revision id the mirror was built from.
    tag : str or None, optional
        The Repository tag naming the revision, when one exists.
    lexicon_manifest_hash : str or None, optional
        The content hash of the vendored lexicon tree, from the manifest.
    layers_version : str or None, optional
        The Layers lexicon version recorded in the manifest.
    license : str or None, optional
        The license identifier from the ``corpus`` record.
    name : str or None, optional
        The corpus name from the ``corpus`` record.
    """

    corpus_uri: str | None = dx.field(
        default=None,
        description="AT-URI of the source corpus record",
    )
    revision: str | None = dx.field(
        default=None,
        description="didactic Repository revision the mirror was built from",
    )
    tag: str | None = dx.field(
        default=None,
        description="Repository tag naming the revision",
    )
    lexicon_manifest_hash: str | None = dx.field(
        default=None,
        description="content hash of the vendored lexicon tree",
    )
    layers_version: str | None = dx.field(
        default=None,
        description="Layers lexicon version from the manifest",
    )
    license: str | None = dx.field(
        default=None,
        description="license identifier from the corpus record",
    )
    name: str | None = dx.field(
        default=None,
        description="corpus name from the corpus record",
    )


def _read_manifest() -> dict[str, str]:
    """Read the vendored lexicon manifest's provenance section.

    Returns
    -------
    dict of str to str
        The manifest hash under ``"lexicon_tree_hash"`` and the Layers version
        under ``"layers_version"``; missing keys are omitted.
    """
    resource = files(_MANIFEST_PACKAGE) / _MANIFEST_NAME
    parsed = tomllib.loads(resource.read_text(encoding="utf-8"))
    provenance = parsed.get("provenance", {})
    result: dict[str, str] = {}
    tree_hash = provenance.get("lexicon_tree_hash")
    if isinstance(tree_hash, str):
        result["lexicon_tree_hash"] = tree_hash
    version = provenance.get("layers_version")
    if isinstance(version, str):
        result["layers_version"] = version
    return result


def provenance_bundle(
    *,
    corpus_uri: str | None = None,
    revision: str | None = None,
    tag: str | None = None,
    license: str | None = None,  # noqa: A002 - mirrors the corpus record field name
    name: str | None = None,
) -> ProvenanceBundle:
    """Assemble a provenance bundle, filling the lexicon manifest fields.

    The lexicon manifest hash and Layers version are read from the vendored
    manifest packaged with lairs, so a mirror always records the schema version
    it was generated against; the remaining fields are supplied by the caller
    from the corpus record and the Repository revision being mirrored.

    Parameters
    ----------
    corpus_uri : str or None, optional
        The AT-URI of the source ``corpus`` record.
    revision : str or None, optional
        The Repository revision id the mirror was built from.
    tag : str or None, optional
        The Repository tag naming the revision.
    license : str or None, optional
        The license identifier from the ``corpus`` record.
    name : str or None, optional
        The corpus name from the ``corpus`` record.

    Returns
    -------
    ProvenanceBundle
        The assembled bundle with the lexicon manifest fields filled in.
    """
    manifest = _read_manifest()
    return ProvenanceBundle(
        corpus_uri=corpus_uri,
        revision=revision,
        tag=tag,
        lexicon_manifest_hash=manifest.get("lexicon_tree_hash"),
        layers_version=manifest.get("layers_version"),
        license=license,
        name=name,
    )


def _card_line(label: str, value: str | None) -> str:
    """Return a single markdown bullet for a provenance field, or empty when unset.

    Parameters
    ----------
    label : str
        The human-readable field label.
    value : str or None
        The field value, or ``None`` when unset.

    Returns
    -------
    str
        A markdown bullet line ending in a newline, or an empty string when the
        value is unset.
    """
    if value is None:
        return ""
    return f"- **{label}:** {value}\n"


def dataset_card(bundle: ProvenanceBundle) -> str:
    """Render a markdown dataset card from a provenance bundle.

    The card documents the canonical sources of the mirror so a reader can trace
    it back to the PDS and the Repository, which remain authoritative. Only the
    fields that are set appear, so a sparse bundle yields a compact card.

    Parameters
    ----------
    bundle : ProvenanceBundle
        The provenance to render.

    Returns
    -------
    str
        The rendered markdown dataset card.
    """
    heading = bundle.name or "lairs corpus mirror"
    lines = [
        f"# {heading}\n",
        "\n",
        (
            "This dataset is a HuggingFace Hub mirror of a Layers corpus exported "
            "by lairs. The canonical sources are the PDS and the didactic "
            "Repository; this mirror is reproducible from the provenance below.\n"
        ),
        "\n",
        "## Provenance\n",
        "\n",
        _card_line("Corpus AT-URI", bundle.corpus_uri),
        _card_line("Repository revision", bundle.revision),
        _card_line("Repository tag", bundle.tag),
        _card_line("Lexicon manifest hash", bundle.lexicon_manifest_hash),
        _card_line("Layers version", bundle.layers_version),
        _card_line("License", bundle.license),
    ]
    return "".join(lines)


def push_to_hub(
    view: pa.Table,
    repo_id: str,
    *,
    private: bool = False,
    provenance: ProvenanceBundle | None = None,
) -> str:
    """Push an Arrow view to the Hub with a provenance dataset card.

    The Arrow view is written as the dataset's data (Arrow/Parquet shards) and
    the provenance bundle is rendered into the dataset card so the mirror records
    its canonical sources. The Hub is a mirror target only; the PDS and the
    Repository stay canonical.

    Parameters
    ----------
    view : pyarrow.Table
        The Arrow view to push.
    repo_id : str
        The target Hub dataset repository identifier (``"org/name"``).
    private : bool, optional
        Whether to create a private repository.
    provenance : ProvenanceBundle or None, optional
        The provenance to render into the dataset card. When omitted, a bundle
        carrying only the vendored lexicon manifest fields is used.

    Returns
    -------
    str
        The URL of the pushed dataset on the Hub.

    Raises
    ------
    ImportError
        When the optional ``datasets`` or ``huggingface_hub`` dependency is not
        installed.
    """
    datasets = _import_datasets()
    hub = _import_hub()
    bundle = provenance if provenance is not None else provenance_bundle()

    dataset = datasets.Dataset(view)
    dataset.push_to_hub(repo_id, private=private)

    api = hub.HfApi()
    api.upload_file(
        path_or_fileobj=dataset_card(bundle).encode("utf-8"),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset",
    )
    return hub.hf_hub_url(repo_id, "README.md", repo_type="dataset")


def load_from_hub(repo_id: str, *, revision: str | None = None) -> Dataset:
    """Load a mirrored dataset back from the Hub.

    Parameters
    ----------
    repo_id : str
        The Hub dataset repository identifier.
    revision : str or None, optional
        A Hub revision (branch, tag, or commit) to read.

    Returns
    -------
    datasets.Dataset
        The loaded dataset.

    Raises
    ------
    ImportError
        When the optional ``datasets`` dependency is not installed.
    """
    datasets = _import_datasets()
    return datasets.load_dataset(repo_id, revision=revision)


def _import_datasets() -> _DatasetsModule:
    """Import the optional ``datasets`` module, with a clear error when absent.

    Returns
    -------
    _DatasetsModule
        The imported ``datasets`` module, narrowed to the surface used here.

    Raises
    ------
    ImportError
        When the ``datasets`` package is not installed.
    """
    try:
        import datasets  # noqa: PLC0415
    except ImportError as exc:
        msg = (
            "the HuggingFace Hub integration requires the optional 'lairs[hf]' "
            "extra (datasets)"
        )
        raise ImportError(msg) from exc
    # the live module supplies the protocol surface, but the checker cannot
    # structurally match a runtime module object against the protocol.
    return datasets  # ty: ignore[invalid-return-type]


def _import_hub() -> _HubModule:
    """Import the optional ``huggingface_hub`` module, with a clear error.

    Returns
    -------
    _HubModule
        The imported ``huggingface_hub`` module, narrowed to the surface used
        here.

    Raises
    ------
    ImportError
        When the ``huggingface_hub`` package is not installed.
    """
    try:
        import huggingface_hub  # noqa: PLC0415
    except ImportError as exc:
        msg = (
            "the HuggingFace Hub integration requires the optional 'lairs[hf]' "
            "extra (huggingface_hub)"
        )
        raise ImportError(msg) from exc
    # the live module supplies the protocol surface, but the checker cannot
    # structurally match a runtime module object against the protocol.
    return huggingface_hub  # ty: ignore[invalid-return-type]


if TYPE_CHECKING:
    from typing import Protocol

    from huggingface_hub import HfApi

    class _DatasetsModule(Protocol):
        """The slice of the ``datasets`` module surface the Hub functions use."""

        Dataset: type[Dataset]

        def load_dataset(self, path: str, *, revision: str | None = ...) -> Dataset:
            """Load a dataset by Hub repository id."""
            ...

    class _HubModule(Protocol):
        """The slice of the ``huggingface_hub`` module surface used here."""

        HfApi: type[HfApi]

        def hf_hub_url(
            self,
            repo_id: str,
            filename: str,
            *,
            repo_type: str | None = ...,
        ) -> str:
            """Return the canonical URL of a file in a Hub repository."""
            ...
