"""Console entry point for lairs.

Exposes the ``lairs`` command for vendoring lexicons, regenerating models,
pulling and materializing corpora, publishing, and inspecting records. The
interface is built on the standard-library :mod:`argparse`, so it adds no
command-line dependency; each subcommand dispatches to the finished component
calls (codegen, the authoring publish/pull workflow, the store materializer, and
the corpus loader).

Subcommands
-----------
vendor
    Refresh the vendored ``pub/layers`` lexicon tree from a local Layers
    checkout and rewrite ``MANIFEST.toml`` provenance.
gen
    Regenerate the committed record models from the vendored lexicons; ``gen
    --check`` is the drift gate and exits non-zero when the committed modules are
    stale.
pull
    Ingest an account's Layers records from a PDS into a local Repository.
materialize
    Build the Arrow/Parquet views of a corpus loaded from a PDS.
publish
    Plan and (with explicit confirmation) apply the minimal write set that makes
    a PDS match a local Repository revision; a dry-run plan is the default.
inspect
    Print a per-record-type summary of a corpus loaded from a PDS.
"""

# ruff: noqa: T201  (a console entry point's job is to print to stdout)

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lairs._codegen import pipeline
from lairs._codegen.manifest import Manifest, load_manifest

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.author.publish import PublishPlan

__all__ = ["main"]

# the package-relative location of the vendored lexicons and generated models.
_PACKAGE_ROOT = Path(__file__).resolve().parent
_LEXICON_ROOT = _PACKAGE_ROOT / "lexicons"
_GENERATED_ROOT = _PACKAGE_ROOT / "records" / "_generated"
_MANIFEST_NAME = "MANIFEST.toml"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the lairs command-line interface.

    Parameters
    ----------
    argv : collections.abc.Sequence of str or None, optional
        The argument vector, excluding the program name; defaults to the
        process arguments.

    Returns
    -------
    int
        The process exit code: ``0`` on success, non-zero on failure or on a
        drift-gate mismatch.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every subcommand.

    Returns
    -------
    argparse.ArgumentParser
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="lairs",
        description="Vendor lexicons, generate models, and work with Layers corpora.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    _add_vendor(subparsers)
    _add_gen(subparsers)
    _add_pull(subparsers)
    _add_materialize(subparsers)
    _add_publish(subparsers)
    _add_inspect(subparsers)
    return parser


# argparse's subparsers action is typed only loosely upstream; the helper alias
# keeps the per-command builders readable without naming a private argparse type.
type _Subparsers = argparse._SubParsersAction[argparse.ArgumentParser]  # noqa: SLF001


def _add_vendor(subparsers: _Subparsers) -> None:
    """Register the ``vendor`` subcommand."""
    sub = subparsers.add_parser(
        "vendor",
        help="refresh the vendored lexicon tree from a Layers checkout",
        description=(
            "Copy a 'lexicons/pub/layers' tree from a local Layers checkout into "
            "lairs/lexicons and rewrite MANIFEST.toml. Fetching by a git ref or "
            "tag is a thin wrapper over this same copy-and-manifest step: check "
            "out the ref first, then point --from at its lexicons/pub/layers."
        ),
    )
    sub.add_argument(
        "--from",
        dest="source",
        required=True,
        type=Path,
        help="path to a Layers 'lexicons/pub/layers' tree to vendor from",
    )
    sub.add_argument(
        "--layers-version",
        default=None,
        help="upstream Layers release version to record (default: keep existing)",
    )
    sub.add_argument(
        "--layers-git-sha",
        default=None,
        help="upstream Layers git revision to record (default: keep existing)",
    )
    sub.add_argument(
        "--vendored-at",
        default=None,
        help="ISO date to record as vendored_at (default: keep existing)",
    )
    sub.set_defaults(handler=_run_vendor)


def _add_gen(subparsers: _Subparsers) -> None:
    """Register the ``gen`` subcommand."""
    sub = subparsers.add_parser(
        "gen",
        help="regenerate record models from the vendored lexicons",
        description=(
            "Generate the committed record models from the vendored lexicons. "
            "With --check, compare the committed modules against a fresh "
            "generation and exit non-zero when they are stale (the CI drift gate)."
        ),
    )
    sub.add_argument(
        "--check",
        action="store_true",
        help="check committed modules for drift instead of writing them",
    )
    sub.set_defaults(handler=_run_gen)


def _add_pull(subparsers: _Subparsers) -> None:
    """Register the ``pull`` subcommand."""
    sub = subparsers.add_parser(
        "pull",
        help="ingest an account's Layers records into a local Repository",
        description=(
            "Read every Layers collection of an account from its PDS and stage "
            "the records into a local Repository for a git-like round trip."
        ),
    )
    sub.add_argument("did", help="the account DID to pull from")
    sub.add_argument(
        "--endpoint",
        required=True,
        help="the base URL of the account's PDS",
    )
    sub.add_argument(
        "--into",
        required=True,
        type=Path,
        help="the local Repository directory to populate",
    )
    sub.add_argument(
        "--message",
        default="pull layers records",
        help="commit message for the pulled snapshot",
    )
    sub.set_defaults(handler=_run_pull)


def _add_materialize(subparsers: _Subparsers) -> None:
    """Register the ``materialize`` subcommand."""
    sub = subparsers.add_parser(
        "materialize",
        help="build Arrow/Parquet views of a corpus",
        description=(
            "Load a corpus from a PDS and write its normalized Arrow/Parquet "
            "views (expressions, annotations) to an output directory."
        ),
    )
    sub.add_argument("uri", help="the corpus AT-URI to materialize")
    sub.add_argument(
        "--endpoint",
        required=True,
        help="the base URL of the PDS to load from",
    )
    sub.add_argument(
        "--out",
        required=True,
        type=Path,
        help="the output directory for the Parquet views",
    )
    sub.set_defaults(handler=_run_materialize)


def _add_publish(subparsers: _Subparsers) -> None:
    """Register the ``publish`` subcommand."""
    sub = subparsers.add_parser(
        "publish",
        help="plan or apply writes to make a PDS match a local revision",
        description=(
            "Diff a local Repository revision against a PDS and emit the minimal "
            "applyWrites plan. Publishing is a dry run by default; pass --yes to "
            "actually write to the PDS."
        ),
    )
    sub.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="the local Repository directory holding the revision",
    )
    sub.add_argument(
        "--revision",
        default="HEAD",
        help="the revision (commit or tag) to publish (default: HEAD)",
    )
    sub.add_argument(
        "--to",
        required=True,
        help="the target repository DID to publish to",
    )
    sub.add_argument(
        "--endpoint",
        default=None,
        help="the base URL of the target PDS (required with --yes)",
    )
    sub.add_argument(
        "--yes",
        action="store_true",
        help="actually apply the writes instead of only showing the plan",
    )
    sub.set_defaults(handler=_run_publish)


def _add_inspect(subparsers: _Subparsers) -> None:
    """Register the ``inspect`` subcommand."""
    sub = subparsers.add_parser(
        "inspect",
        help="summarize a corpus loaded from a PDS",
        description=(
            "Load a corpus from a PDS and print a per-record-type count summary."
        ),
    )
    sub.add_argument("uri", help="the corpus AT-URI to inspect")
    sub.add_argument(
        "--endpoint",
        required=True,
        help="the base URL of the PDS to load from",
    )
    sub.set_defaults(handler=_run_inspect)


def _run_vendor(args: argparse.Namespace) -> int:
    """Handle ``lairs vendor``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success, ``1`` when the source tree is missing.
    """
    source: Path = args.source
    if not source.is_dir():
        print(f"error: source tree not found: {source}", file=sys.stderr)
        return 1
    manifest = _vendor_tree(
        source,
        layers_version=args.layers_version,
        layers_git_sha=args.layers_git_sha,
        vendored_at=args.vendored_at,
    )
    print(f"vendored {manifest.lexicon_files} lexicon files into {_LEXICON_ROOT}")
    print(f"lexicon_tree_hash = {manifest.lexicon_tree_hash}")
    print("run 'lairs gen' to regenerate the record models from the vendored tree")
    return 0


def _vendor_tree(
    source: Path,
    *,
    layers_version: str | None,
    layers_git_sha: str | None,
    vendored_at: str | None,
) -> Manifest:
    """Copy a Layers lexicon tree into the package and rewrite the manifest.

    The copied tree replaces ``lairs/lexicons/pub/layers``. The manifest hash is
    recomputed from the new tree content; when that content is byte-identical to
    the tree already vendored, the existing hash and vendoring date are kept so a
    no-op re-vendor does not invalidate the committed generated models.

    Parameters
    ----------
    source : pathlib.Path
        The ``lexicons/pub/layers`` tree to vendor from.
    layers_version : str or None
        The Layers release version to record, or ``None`` to keep the existing.
    layers_git_sha : str or None
        The Layers git revision to record, or ``None`` to keep the existing.
    vendored_at : str or None
        The ISO date to record, or ``None`` to keep the existing.

    Returns
    -------
    lairs._codegen.manifest.Manifest
        The rewritten manifest model.
    """
    existing = _load_existing_manifest()
    target = _LEXICON_ROOT / "pub" / "layers"
    before = _tree_hash(target) if target.exists() else ""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    after = _tree_hash(target)
    unchanged = after == before
    manifest = Manifest(
        layers_git_sha=layers_git_sha
        if layers_git_sha is not None
        else existing.layers_git_sha,
        layers_version=layers_version
        if layers_version is not None
        else existing.layers_version,
        vendored_at=vendored_at if vendored_at is not None else existing.vendored_at,
        lexicon_tree_hash=existing.lexicon_tree_hash if unchanged else after,
        lexicon_files=_count_lexicon_files(),
        record_types=_count_record_types(),
    )
    _write_manifest(manifest)
    return manifest


def _load_existing_manifest() -> Manifest:
    """Return the current manifest, or an empty default when absent.

    Returns
    -------
    lairs._codegen.manifest.Manifest
        The existing manifest model, or one with empty provenance.
    """
    path = _LEXICON_ROOT / _MANIFEST_NAME
    if path.exists():
        return load_manifest(path)
    return Manifest(
        layers_git_sha="",
        layers_version="",
        vendored_at="",
        lexicon_tree_hash="",
    )


def _tree_hash(root: Path) -> str:
    """Return a deterministic content hash of a lexicon tree.

    The hash is the SHA-256 over the sorted ``"<posix-relpath>:<file-sha256>"``
    lines of every ``*.json`` file under the tree, so it depends only on file
    paths and contents and is stable across machines.

    Parameters
    ----------
    root : pathlib.Path
        The tree root to hash (the directory holding the lexicon JSON files).

    Returns
    -------
    str
        The hex SHA-256 of the tree.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.json"), key=str):
        relative = path.relative_to(root).as_posix()
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{relative}:{file_digest}\n".encode())
    return digest.hexdigest()


def _count_lexicon_files() -> int:
    """Return the number of vendored lexicon JSON files.

    Returns
    -------
    int
        The count of ``*.json`` files under the vendored ``pub`` tree.
    """
    pub = _LEXICON_ROOT / "pub"
    if not pub.exists():
        return 0
    return sum(1 for _ in pub.rglob("*.json"))


def _count_record_types() -> int:
    """Return the number of record definitions across the vendored tree.

    A lexicon document defines a record when one of its ``defs`` entries has the
    ``record`` type; the count mirrors the manifest's ``record_types`` field.

    Returns
    -------
    int
        The number of record-typed definitions across the vendored lexicons.
    """
    import json  # noqa: PLC0415  (only the vendor path reads lexicon json)

    pub = _LEXICON_ROOT / "pub"
    if not pub.exists():
        return 0
    count = 0
    for path in pub.rglob("*.json"):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        defs = loaded.get("defs")
        if not isinstance(defs, dict):
            continue
        for definition in defs.values():
            if isinstance(definition, dict) and definition.get("type") == "record":
                count += 1
    return count


def _write_manifest(manifest: Manifest) -> None:
    """Serialise a manifest model back to the vendoring TOML form.

    Parameters
    ----------
    manifest : lairs._codegen.manifest.Manifest
        The manifest to write.
    """
    lines = [
        "# Vendoring manifest for the Layers lexicon tree.",
        "#",
        "# This file records the provenance of the vendored `pub/layers/**` "
        "lexicon JSON",
        "# so a regeneration is reproducible and auditable. It is rewritten by",
        "# `lairs vendor --from <path>`.",
        "#",
        "# The runtime representation of this manifest is a didactic model; this TOML",
        "# file is its serialised, reviewable form.",
        "",
        "[provenance]",
        f'layers_git_sha = "{manifest.layers_git_sha}"',
        f'layers_version = "{manifest.layers_version}"',
        f'vendored_at = "{manifest.vendored_at}"',
        f'lexicon_tree_hash = "{manifest.lexicon_tree_hash}"',
        "",
        "[counts]",
        f"lexicon_files = {manifest.lexicon_files}",
        f"record_types = {manifest.record_types}",
        "",
    ]
    (_LEXICON_ROOT / _MANIFEST_NAME).write_text("\n".join(lines), encoding="utf-8")


def _run_gen(args: argparse.Namespace) -> int:
    """Handle ``lairs gen`` and ``lairs gen --check``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success or a clean drift check; ``1`` when ``--check`` finds
        stale committed modules.
    """
    if args.check:
        if pipeline.check(_LEXICON_ROOT, _GENERATED_ROOT):
            print("generated record models are up to date")
            return 0
        print(
            "generated record models are stale; run 'lairs gen' to regenerate",
            file=sys.stderr,
        )
        return 1
    written = pipeline.generate(_LEXICON_ROOT, _GENERATED_ROOT)
    print(f"generated {len(written)} module(s) into {_GENERATED_ROOT}")
    return 0


def _run_pull(args: argparse.Namespace) -> int:
    """Handle ``lairs pull``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success.
    """
    from lairs.author.publish import pull  # noqa: PLC0415  (defers httpx-backed deps)
    from lairs.store.repository import Repository  # noqa: PLC0415

    into: Path = args.into
    repo = Repository.init(into)
    pull(args.did, endpoint=args.endpoint, into=repo)
    uris = repo.staged_uris()
    print(f"pulled {len(uris)} record(s) from {args.did} into {into}")
    if not uris:
        print("nothing to commit: no records were pulled")
        return 0
    revision = repo.commit(args.message)
    print(f"committed snapshot {revision}")
    return 0


def _run_materialize(args: argparse.Namespace) -> int:
    """Handle ``lairs materialize``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success.
    """
    from lairs.atproto.pds import PdsClient  # noqa: PLC0415  (defers httpx import)
    from lairs.data import load_corpus  # noqa: PLC0415

    out: Path = args.out
    with PdsClient(args.endpoint) as client:
        corpus = load_corpus(args.uri, source="pds", pds_client=client)
    written = corpus.materialize(out)
    print(f"materialized {len(written)} view(s) into {out}")
    for path in written:
        print(f"  {path}")
    return 0


def _run_publish(args: argparse.Namespace) -> int:
    """Handle ``lairs publish`` (dry-run by default).

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success; ``1`` when a live publish is requested without an
        endpoint.
    """
    from lairs.author.publish import publish  # noqa: PLC0415  (defers httpx import)
    from lairs.store.repository import Repository  # noqa: PLC0415

    if args.yes and args.endpoint is None:
        print("error: --yes requires --endpoint to write to a PDS", file=sys.stderr)
        return 1
    repo = Repository.open(args.repo)
    dry_run = not args.yes
    plan = publish(
        repo,
        args.revision,
        to=args.to,
        endpoint=args.endpoint,
        dry_run=dry_run,
    )
    _print_plan(plan, dry_run=dry_run)
    return 0


def _print_plan(plan: PublishPlan, *, dry_run: bool) -> None:
    """Print a publish plan summary.

    Parameters
    ----------
    plan : lairs.author.publish.PublishPlan
        The plan to summarize.
    dry_run : bool
        Whether the plan was a dry run (planned) or applied.
    """
    creates = len(plan.creates)
    updates = len(plan.updates)
    deletes = len(plan.deletes)
    verb = "planned" if dry_run else "applied"
    print(f"publish plan ({verb}) for {plan.repo} at {plan.revision}:")
    print(f"  creates: {creates}")
    print(f"  updates: {updates}")
    print(f"  deletes: {deletes}")
    if dry_run and not plan.is_empty():
        print("dry run: pass --yes --endpoint <pds> to apply these writes")


def _run_inspect(args: argparse.Namespace) -> int:
    """Handle ``lairs inspect``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success.
    """
    from lairs.atproto.pds import PdsClient  # noqa: PLC0415  (defers httpx import)
    from lairs.data import load_corpus  # noqa: PLC0415

    with PdsClient(args.endpoint) as client:
        corpus = load_corpus(args.uri, source="pds", pds_client=client)
    counts: dict[str, int] = {}
    for uri in corpus.pool.uris():
        nsid = _nsid_of(uri)
        counts[nsid] = counts.get(nsid, 0) + 1
    total = sum(counts.values())
    print(f"corpus {args.uri}: {total} record(s)")
    for nsid in sorted(counts):
        print(f"  {nsid}: {counts[nsid]}")
    return 0


def _nsid_of(uri: str) -> str:
    """Return the collection NSID embedded in an AT-URI.

    An AT-URI has the form ``at://<authority>/<collection>/<rkey>``; the
    collection segment is the lexicon NSID.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The collection NSID, or the empty string when none is present.
    """
    body = uri.removeprefix("at://")
    parts = body.split("/")
    minimum_parts_with_collection = 2
    if len(parts) >= minimum_parts_with_collection:
        return parts[1]
    return ""
