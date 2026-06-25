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
    from datasets import Dataset, DatasetDict

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


def _yaml_front_matter(bundle: ProvenanceBundle) -> str:
    """Render the Hub dataset-card YAML front-matter block from a bundle.

    The HuggingFace dataset viewer and Hub metadata indexing read the README's
    leading YAML block, so the machine-readable license and the corpus's
    canonical AT-URI are surfaced there rather than only in prose. Only fields
    that are set appear, and the block is omitted entirely when nothing is set,
    so a sparse bundle does not emit an empty header.

    Parameters
    ----------
    bundle : ProvenanceBundle
        The provenance to render into the front-matter.

    Returns
    -------
    str
        The ``---``-delimited YAML block ending in a newline, or an empty string
        when no front-matter field is set.
    """
    lines: list[str] = []
    if bundle.license is not None:
        lines.append(f"license: {bundle.license}\n")
    if bundle.corpus_uri is not None:
        lines.append("source_datasets:\n")
        lines.append(f"  - {bundle.corpus_uri}\n")
    if bundle.tag is not None:
        lines.append("tags:\n")
        lines.append("  - lairs\n")
        lines.append("  - layers\n")
    if not lines:
        return ""
    return "---\n" + "".join(lines) + "---\n"


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
    it back to the PDS and the Repository, which remain authoritative. A leading
    YAML front-matter block carries the machine-readable license and source
    AT-URI for the Hub dataset viewer and metadata indexing; the prose section
    below repeats the full provenance. Only the fields that are set appear, so a
    sparse bundle yields a compact card.

    Parameters
    ----------
    bundle : ProvenanceBundle
        The provenance to render.

    Returns
    -------
    str
        The rendered markdown dataset card, prefixed with a YAML front-matter
        block when any front-matter field is set.
    """
    heading = bundle.name or "lairs corpus mirror"
    lines = [
        _yaml_front_matter(bundle),
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


def push_to_hub(  # noqa: PLR0913  (mirror target plus auth, split, and config knobs)
    view: pa.Table,
    repo_id: str,
    *,
    private: bool = False,
    provenance: ProvenanceBundle | None = None,
    token: str | None = None,
    split: str = "train",
    config_name: str = "default",
) -> str:
    """Push an Arrow view to the Hub with a provenance dataset card.

    The Arrow view is written as the dataset's data (Arrow/Parquet shards) and
    the provenance bundle is rendered into the dataset card so the mirror records
    its canonical sources. The Hub is a mirror target only; the PDS and the
    Repository stay canonical.

    The push is two Hub commits: ``datasets`` writes the data shards, then the
    provenance card is uploaded as a second commit. These are not atomic; if the
    card upload fails after the data is pushed, the mirror exists without its
    provenance and the card upload must be retried. The data and card never
    diverge in content, so a retry is always safe.

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
    token : str or None, optional
        A HuggingFace access token with write scope. When omitted, the ambient
        login state (a prior ``huggingface-cli login`` or the ``HF_TOKEN``
        environment variable) is used; an unauthenticated caller surfaces a
        ``huggingface_hub`` authentication error from the underlying push.
    split : str, optional
        The dataset split name to write the shards under.
    config_name : str, optional
        The dataset configuration (subset) name to write the shards under.

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
    dataset.push_to_hub(
        repo_id,
        config_name=config_name,
        split=split,
        private=private,
        token=token,
    )

    api = hub.HfApi(token=token)
    api.upload_file(
        path_or_fileobj=dataset_card(bundle).encode("utf-8"),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset",
    )
    return hub.hf_hub_url(repo_id, "README.md", repo_type="dataset")


def load_from_hub(
    repo_id: str,
    *,
    split: str | None = None,
    revision: str | None = None,
    token: str | None = None,
) -> Dataset | DatasetDict:
    """Load a mirrored dataset back from the Hub.

    When ``split`` is given, a single :class:`datasets.Dataset` is returned; when
    it is omitted, ``datasets.load_dataset`` returns a
    :class:`datasets.DatasetDict` keyed by split name for a multi-split
    repository (and a :class:`datasets.Dataset` for a single-split repository).
    Callers that need a concrete ``Dataset`` should pass ``split`` or index the
    returned dict by split name.

    Parameters
    ----------
    repo_id : str
        The Hub dataset repository identifier.
    split : str or None, optional
        A single split to load (for example ``"train"``). When set, a
        ``datasets.Dataset`` is returned; when omitted, the whole
        ``DatasetDict`` is returned for a multi-split repository.
    revision : str or None, optional
        A Hub revision (branch, tag, or commit) to read.
    token : str or None, optional
        A HuggingFace access token for a private or gated repository. When
        omitted, the ambient login state is used.

    Returns
    -------
    datasets.Dataset or datasets.DatasetDict
        The loaded dataset when ``split`` is given (or the repository is
        single-split), otherwise the split-keyed mapping.

    Raises
    ------
    ImportError
        When the optional ``datasets`` dependency is not installed.
    """
    datasets = _import_datasets()
    return datasets.load_dataset(
        repo_id,
        split=split,
        revision=revision,
        token=token,
    )


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

        def load_dataset(
            self,
            path: str,
            *,
            split: str | None = ...,
            revision: str | None = ...,
            token: str | None = ...,
        ) -> Dataset | DatasetDict:
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
