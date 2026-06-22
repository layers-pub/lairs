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
datasets
    Resolve a handle or DID and list its datasets, one row per corpus.
toc
    Resolve a handle or DID and print its repository collection inventory.
search
    Fan out over a seed of handles or DIDs and list matching datasets.
index
    Build, refresh, search, and diff a local dataset index.
login
    Authenticate to a PDS with an app password and save the session.
logout
    Forget the saved session.
whoami
    Print the saved session's identity.
"""

# ruff: noqa: T201  (a console entry point's job is to print to stdout)

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from lairs import data, discovery
from lairs._aturi import nsid_of as _nsid_of
from lairs._codegen import pipeline
from lairs._codegen.manifest import Manifest, load_manifest
from lairs.atproto import auth
from lairs.atproto.identity import IdentityError
from lairs.atproto.pds import PdsClient
from lairs.author import publish as publish_ops
from lairs.discovery import accelerator
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lairs.author.publish import PublishPlan
    from lairs.discovery import CardDiff, CrawlReport, SearchHit, SearchQuery
    from lairs.discovery.models import (
        DatasetFilter,
        DatasetSummary,
        RepoTableOfContents,
    )

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
    _add_datasets(subparsers)
    _add_toc(subparsers)
    _add_search(subparsers)
    _add_index(subparsers)
    _add_login(subparsers)
    _add_logout(subparsers)
    _add_whoami(subparsers)
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
        default=None,
        help="the target repository DID (defaults to the logged-in account)",
    )
    sub.add_argument(
        "--endpoint",
        default=None,
        help="the base URL of the target PDS (defaults to the logged-in PDS)",
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
    into: Path = args.into
    repo = Repository.init(into)
    publish_ops.pull(args.did, endpoint=args.endpoint, into=repo)
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
    out: Path = args.out
    with PdsClient(args.endpoint) as client:
        corpus = data.load_corpus(args.uri, source="pds", pds_client=client)
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
    store = auth.SessionStore()
    session = store.load()
    target = args.to or (session.did if session is not None else None)
    endpoint = args.endpoint or (session.pds_endpoint if session is not None else None)
    if target is None:
        print("error: --to is required (or run 'lairs login')", file=sys.stderr)
        return 1
    if args.yes and endpoint is None:
        print(
            "error: --yes requires --endpoint or a logged-in session",
            file=sys.stderr,
        )
        return 1
    if args.yes and session is None:
        print(
            "error: --yes requires a logged-in session (run 'lairs login')",
            file=sys.stderr,
        )
        return 1
    repo = Repository.open(args.repo)
    dry_run = not args.yes
    client = None
    if args.yes and session is not None:
        client = auth.authed_client(session, store=store)
    try:
        plan = publish_ops.publish(
            repo,
            args.revision,
            to=target,
            endpoint=endpoint,
            client=client,
            dry_run=dry_run,
        )
    finally:
        if client is not None:
            client.close()
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
    with PdsClient(args.endpoint) as client:
        corpus = data.load_corpus(args.uri, source="pds", pds_client=client)
    counts: dict[str, int] = {}
    for uri in corpus.pool.uris():
        nsid = _nsid_of(uri)
        counts[nsid] = counts.get(nsid, 0) + 1
    total = sum(counts.values())
    print(f"corpus {args.uri}: {total} record(s)")
    for nsid in sorted(counts):
        print(f"  {nsid}: {counts[nsid]}")
    return 0


def _add_filter_args(sub: argparse.ArgumentParser) -> None:
    """Add the shared dataset facet flags to a subparser."""
    sub.add_argument("--language", default=None, help="filter by language tag")
    sub.add_argument("--domain", default=None, help="filter by domain slug")
    sub.add_argument(
        "--license",
        default=None,
        help="filter by license facet (SPDX slug or expression)",
    )
    sub.add_argument(
        "--min-expressions",
        type=int,
        default=None,
        dest="min_expressions",
        help="keep corpora with at least this many expressions",
    )
    sub.add_argument(
        "--max-expressions",
        type=int,
        default=None,
        dest="max_expressions",
        help="keep corpora with at most this many expressions",
    )
    sub.add_argument(
        "--text",
        default=None,
        help="case-insensitive substring over name and description",
    )
    sub.add_argument(
        "--has-adjudication",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="has_adjudication",
        help="require corpora to declare (or not) an adjudication step",
    )


def _dataset_filter(args: argparse.Namespace) -> DatasetFilter:
    """Build a ``DatasetFilter`` from the parsed facet flags."""
    return discovery.DatasetFilter(
        language=args.language,
        domain=args.domain,
        license=args.license,
        min_expression_count=args.min_expressions,
        max_expression_count=args.max_expressions,
        text=args.text,
        has_adjudication=args.has_adjudication,
    )


def _print_datasets(rows: Sequence[DatasetSummary], *, as_json: bool) -> None:
    """Print dataset summaries as a readable table or JSON array."""
    if as_json:
        payload = [json.loads(row.model_dump_json()) for row in rows]
        print(json.dumps(payload, indent=2))
        return
    if not rows:
        print("no datasets found")
        return
    for row in rows:
        who = row.handle or row.did
        domain = row.domain or "-"
        language = row.language or "-"
        count = row.expression_count if row.expression_count is not None else "-"
        license_id = row.license or "-"
        print(f"{row.name}  [{domain}/{language}]  {count} expr  {license_id}")
        print(f"  {who}  {row.uri}")


def _print_toc(toc: RepoTableOfContents, *, as_json: bool) -> None:
    """Print a repository table of contents as a readable list or JSON object."""
    if as_json:
        print(json.dumps(json.loads(toc.model_dump_json()), indent=2))
        return
    label = f"{toc.did} ({toc.handle})" if toc.handle else toc.did
    print(f"repo {label}")
    for collection in toc.collections:
        marker = "*" if collection.is_dataset_like else " "
        count = f"  {collection.count}" if collection.count is not None else ""
        print(f"  [{marker}] {collection.nsid}{count}")


def _add_datasets(subparsers: _Subparsers) -> None:
    """Register the ``datasets`` subcommand."""
    sub = subparsers.add_parser(
        "datasets",
        help="list an actor's datasets",
        description=(
            "Resolve a handle or DID and list its datasets, one row per corpus."
        ),
    )
    sub.add_argument("actor", help="the handle or DID to list datasets for")
    sub.add_argument(
        "--source",
        choices=("auto", "pds", "appview"),
        default="auto",
        help="discovery source (default: auto)",
    )
    sub.add_argument("--appview", default=None, help="appview base URL")
    sub.add_argument("--endpoint", default=None, help="PDS base URL override")
    _add_filter_args(sub)
    sub.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum number of rows to print",
    )
    sub.add_argument(
        "--json",
        action="store_true",
        help="print JSON instead of a table",
    )
    sub.set_defaults(handler=_run_datasets)


def _run_datasets(args: argparse.Namespace) -> int:
    """Handle ``lairs datasets``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success, ``1`` on a resolution or transport failure.
    """
    pds_client = PdsClient(args.endpoint) if args.endpoint else None
    try:
        rows = discovery.list_datasets(
            args.actor,
            source=args.source,
            appview=args.appview,
            filters=_dataset_filter(args),
            pds_client=pds_client,
        )
    except (httpx.HTTPError, IdentityError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if pds_client is not None:
            pds_client.close()
    if args.limit is not None:
        rows = rows[: args.limit]
    _print_datasets(rows, as_json=args.json)
    return 0


def _print_report(report: CrawlReport) -> None:
    """Print a crawl or firehose pass summary."""
    print(
        f"repos seen: {report.repos_seen}, with corpora: {report.repos_with_corpora}",
    )
    print(f"cards built: {report.cards_built}, unchanged: {report.cards_unchanged}")
    for reason in report.skipped:
        print(f"  skipped {reason}")
    if report.revision is not None:
        print(f"committed {report.revision}")


def _print_hits(hits: list[SearchHit]) -> None:
    """Print ranked search hits."""
    if not hits:
        print("no datasets found")
        return
    for hit in hits:
        summary = hit.card.summary
        domain = summary.domain or "-"
        language = summary.language or "-"
        print(f"{hit.score:.1f}  {summary.name}  [{domain}/{language}]  {summary.uri}")


def _print_card_diff(diff: CardDiff) -> None:
    """Print an index diff between two revisions."""
    print(
        f"added: {len(diff.added)}  "
        f"changed: {len(diff.changed)}  "
        f"removed: {len(diff.removed)}",
    )
    for uri in diff.added:
        print(f"  + {uri}")
    for uri in diff.changed:
        print(f"  ~ {uri}")
    for uri in diff.removed:
        print(f"  - {uri}")


def _add_index(subparsers: _Subparsers) -> None:
    """Register the ``index`` subcommand group."""
    index = subparsers.add_parser(
        "index",
        help="build, refresh, search, and diff a local dataset index",
        description=(
            "Maintain a local, searchable dataset index in a panproto "
            "Repository, built from a crawl and kept fresh from the firehose."
        ),
    )
    index_sub = index.add_subparsers(dest="index_command", metavar="index_command")

    build = index_sub.add_parser("build", help="crawl repositories into the index")
    build.add_argument("--into", required=True, type=Path, help="index directory")
    build.add_argument(
        "--endpoint",
        required=True,
        help="the relay or PDS to crawl",
    )
    build.add_argument(
        "--seed-did",
        action="append",
        default=None,
        dest="seed_did",
        help="crawl only this DID (repeatable); default crawls every repo",
    )
    build.add_argument(
        "--max-repos",
        type=int,
        default=None,
        dest="max_repos",
        help="bound on repositories visited",
    )
    build.add_argument(
        "--message",
        default="backfill crawl",
        help="commit message for the crawl snapshot",
    )
    build.set_defaults(handler=_run_index_build)

    update = index_sub.add_parser("update", help="tail the firehose into the index")
    update.add_argument("--index", required=True, type=Path, help="index directory")
    update.add_argument("--relay", required=True, help="the firehose endpoint")
    update.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many events",
    )
    update.set_defaults(handler=_run_index_update)

    search = index_sub.add_parser("search", help="search the local index")
    search.add_argument("--index", required=True, type=Path, help="index directory")
    search.add_argument("query", nargs="?", default=None, help="free-text query")
    search.add_argument("--domain", default=None, help="filter by domain slug")
    search.add_argument("--language", default=None, help="filter by language tag")
    search.add_argument(
        "--license",
        default=None,
        help="filter by license facet (SPDX slug or expression)",
    )
    search.add_argument(
        "--min-expressions",
        type=int,
        default=None,
        dest="min_expressions",
        help="minimum expression count",
    )
    search.add_argument(
        "--max-expressions",
        type=int,
        default=None,
        dest="max_expressions",
        help="maximum expression count",
    )
    search.add_argument("--metric", default=None, help="required quality metric slug")
    search.add_argument(
        "--min-rounds",
        type=int,
        default=None,
        dest="min_rounds",
        help="minimum annotation rounds",
    )
    search.add_argument(
        "--duckdb",
        action="store_true",
        help="pre-filter through the DuckDB accelerator",
    )
    search.set_defaults(handler=_run_index_search)

    diff = index_sub.add_parser("diff", help="diff the index between two revisions")
    diff.add_argument("--index", required=True, type=Path, help="index directory")
    diff.add_argument("base", help="the base revision")
    diff.add_argument("head", help="the head revision")
    diff.set_defaults(handler=_run_index_diff)


def _run_index_build(args: argparse.Namespace) -> int:
    """Handle ``lairs index build``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success, ``1`` on a transport failure.
    """
    index = discovery.DiscoveryIndex.init(args.into)
    with PdsClient(args.endpoint) as client:
        dids = args.seed_did or client.list_repos()
        try:
            report = discovery.build_index(
                index,
                dids,
                describe=client,
                list_corpora=client,
                endpoint=args.endpoint,
                max_repos=args.max_repos,
                message=args.message,
            )
        except httpx.HTTPError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    _print_report(report)
    return 0


def _run_index_update(args: argparse.Namespace) -> int:
    """Handle ``lairs index update``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success, ``1`` on a transport failure.
    """
    index = discovery.DiscoveryIndex.open(args.index)
    try:
        report = discovery.update_index(index, args.relay, limit=args.limit)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_report(report)
    return 0


def _run_index_search(args: argparse.Namespace) -> int:
    """Handle ``lairs index search``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success.
    """
    index = discovery.DiscoveryIndex.open(args.index)
    query: SearchQuery = discovery.SearchQuery(
        text=args.query,
        domain=args.domain,
        language=args.language,
        license=args.license,
        min_expressions=args.min_expressions,
        max_expressions=args.max_expressions,
        annotation_metric=args.metric,
        min_annotation_rounds=args.min_rounds,
    )
    if args.duckdb:
        hits = accelerator.search_accelerated(
            index, query, out_dir=args.index / ".accel"
        )
    else:
        hits = discovery.search(index.cards(), query)
    _print_hits(hits)
    return 0


def _run_index_diff(args: argparse.Namespace) -> int:
    """Handle ``lairs index diff``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success.
    """
    index = discovery.DiscoveryIndex.open(args.index)
    _print_card_diff(index.diff_cards(args.base, args.head))
    return 0


def _add_toc(subparsers: _Subparsers) -> None:
    """Register the ``toc`` subcommand."""
    sub = subparsers.add_parser(
        "toc",
        help="show a repository's collection inventory",
        description=(
            "Resolve a handle or DID and print the collections in its repository, "
            "starring the dataset-shaped ones, without dumping records."
        ),
    )
    sub.add_argument("actor", help="the handle or DID to inventory")
    sub.add_argument(
        "--source",
        choices=("auto", "pds", "appview"),
        default="auto",
        help="discovery source (default: auto)",
    )
    sub.add_argument("--endpoint", default=None, help="PDS base URL override")
    sub.add_argument(
        "--counts",
        action="store_true",
        help="count records per collection (drains each collection)",
    )
    sub.add_argument(
        "--json",
        action="store_true",
        help="print JSON instead of a table",
    )
    sub.set_defaults(handler=_run_toc)


def _run_toc(args: argparse.Namespace) -> int:
    """Handle ``lairs toc``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success, ``1`` on a resolution or transport failure.
    """
    pds_client = PdsClient(args.endpoint) if args.endpoint else None
    try:
        toc = discovery.table_of_contents(
            args.actor,
            source=args.source,
            counts=args.counts,
            pds_client=pds_client,
        )
    except (httpx.HTTPError, IdentityError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if pds_client is not None:
            pds_client.close()
    _print_toc(toc, as_json=args.json)
    return 0


def _add_search(subparsers: _Subparsers) -> None:
    """Register the ``search`` subcommand."""
    sub = subparsers.add_parser(
        "search",
        help="search datasets across a seed of actors",
        description=(
            "Fan out over a seed of handles or DIDs and list the matching "
            "datasets, deduplicated by corpus."
        ),
    )
    sub.add_argument("actors", nargs="+", help="handles or DIDs to search across")
    sub.add_argument(
        "--source",
        choices=("auto", "pds", "appview"),
        default="auto",
        help="discovery source (default: auto)",
    )
    sub.add_argument("--appview", default=None, help="appview base URL")
    _add_filter_args(sub)
    sub.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum number of rows to print",
    )
    sub.add_argument(
        "--json",
        action="store_true",
        help="print JSON instead of a table",
    )
    sub.set_defaults(handler=_run_search)


def _run_search(args: argparse.Namespace) -> int:
    """Handle ``lairs search``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success, ``1`` on a resolution or transport failure.
    """
    try:
        rows = discovery.discover_datasets(
            args.actors,
            source=args.source,
            appview=args.appview,
            filters=_dataset_filter(args),
        )
    except (httpx.HTTPError, IdentityError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.limit is not None:
        rows = rows[: args.limit]
    _print_datasets(rows, as_json=args.json)
    return 0


def _add_login(subparsers: _Subparsers) -> None:
    """Register the ``login`` subcommand."""
    sub = subparsers.add_parser(
        "login",
        help="authenticate to a PDS with an app password",
        description=(
            "Resolve a handle or DID to its PDS, exchange an app password for a "
            "session, and save it so later commands authenticate automatically. "
            "Prefer the LAIRS_APP_PASSWORD environment variable over "
            "--app-password so the secret does not appear in the process list."
        ),
    )
    sub.add_argument("identifier", help="the account handle or DID")
    sub.add_argument(
        "--app-password",
        default=None,
        dest="app_password",
        help="an app password (default: read LAIRS_APP_PASSWORD)",
    )
    sub.add_argument(
        "--pds",
        default=None,
        help="the PDS base URL (skips handle resolution)",
    )
    sub.set_defaults(handler=_run_login)


def _run_login(args: argparse.Namespace) -> int:
    """Handle ``lairs login``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` on success, ``1`` on a missing password or auth failure.
    """
    password = args.app_password or os.environ.get("LAIRS_APP_PASSWORD")
    if not password:
        print(
            "error: provide --app-password or set LAIRS_APP_PASSWORD",
            file=sys.stderr,
        )
        return 1
    try:
        session = auth.login(args.identifier, password, pds=args.pds)
    except (httpx.HTTPError, IdentityError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    store = auth.SessionStore()
    store.save(session)
    print(f"logged in as {session.handle or session.did} ({session.did})")
    print(f"session saved to {store.path}")
    return 0


def _add_logout(subparsers: _Subparsers) -> None:
    """Register the ``logout`` subcommand."""
    sub = subparsers.add_parser(
        "logout",
        help="forget the saved session",
        description="Delete the saved authentication session, if any.",
    )
    sub.set_defaults(handler=_run_logout)


def _run_logout(args: argparse.Namespace) -> int:
    """Handle ``lairs logout``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` always.
    """
    _ = args
    store = auth.SessionStore()
    if store.delete():
        print(f"logged out ({store.path})")
    else:
        print("not logged in")
    return 0


def _add_whoami(subparsers: _Subparsers) -> None:
    """Register the ``whoami`` subcommand."""
    sub = subparsers.add_parser(
        "whoami",
        help="print the saved session's identity",
        description="Print the identity of the saved authentication session.",
    )
    sub.set_defaults(handler=_run_whoami)


def _run_whoami(args: argparse.Namespace) -> int:
    """Handle ``lairs whoami``.

    Parameters
    ----------
    args : argparse.Namespace
        The parsed arguments.

    Returns
    -------
    int
        ``0`` when a session is saved, ``1`` when not logged in.
    """
    _ = args
    session = auth.SessionStore().load()
    if session is None:
        print("not logged in")
        return 1
    print(session.handle or session.did)
    print(f"  did: {session.did}")
    print(f"  pds: {session.pds_endpoint}")
    return 0
