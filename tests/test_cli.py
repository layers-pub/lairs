"""Unit and integration tests for lairs.cli."""

from __future__ import annotations

import datetime
import json
import shutil
from typing import TYPE_CHECKING

import httpx
import pytest

from lairs import cli, discovery
from lairs._codegen.manifest import load_manifest
from lairs.atproto import auth
from lairs.atproto.auth import Session
from lairs.atproto.identity import IdentityError
from lairs.author.publish import PublishPlan
from lairs.data.corpus import Corpus
from lairs.discovery import CardDiff, CrawlReport, SearchHit, SearchQuery
from lairs.discovery.cards import CardFreshness, CardProvenance, DatasetCard
from lairs.discovery.models import (
    CollectionCount,
    DatasetSummary,
    RepoTableOfContents,
)
from lairs.records._generated import expression as expression_records
from lairs.records._generated import media as media_records
from lairs.records._generated import persona as persona_records
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Self

    from conftest import PdsServer

    from lairs.atproto.pds import PdsClient

_NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def test_exports() -> None:
    assert set(cli.__all__) == {"main"}


def test_no_command_prints_help_and_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main([])
    captured = capsys.readouterr()
    assert code == 2
    assert "usage: lairs" in captured.out


def test_help_lists_every_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for command in (
        "vendor",
        "gen",
        "pull",
        "materialize",
        "publish",
        "inspect",
        "datasets",
        "toc",
        "search",
        "index",
        "tui",
        "login",
        "logout",
        "whoami",
    ):
        assert command in out


def test_unknown_command_errors() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["nope"])
    assert excinfo.value.code != 0


# gen ------------------------------------------------------------------------


def test_gen_check_passes_for_current_records(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(["gen", "--check"])
    captured = capsys.readouterr()
    assert code == 0
    assert "up to date" in captured.out


def test_gen_check_fails_when_records_are_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # point the generated root at a copy with one module deliberately corrupted
    # so the drift check finds a mismatch and exits non-zero.
    stale = tmp_path / "_generated"
    shutil.copytree(cli._GENERATED_ROOT, stale)
    (stale / "expression.py").write_text("# stale\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_GENERATED_ROOT", stale)
    code = cli.main(["gen", "--check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "stale" in captured.err


def test_gen_writes_modules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "_generated"
    monkeypatch.setattr(cli, "_GENERATED_ROOT", out)
    code = cli.main(["gen"])
    captured = capsys.readouterr()
    assert code == 0
    assert "generated" in captured.out
    assert (out / "__init__.py").exists()
    assert (out / "expression.py").exists()


# vendor ---------------------------------------------------------------------


def _seed_lexicon_root(root: Path) -> None:
    """Copy the real vendored lexicons and manifest into a temp root."""
    shutil.copytree(cli._LEXICON_ROOT / "pub", root / "pub")
    shutil.copy2(cli._LEXICON_ROOT / cli._MANIFEST_NAME, root / cli._MANIFEST_NAME)


def test_vendor_missing_source_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(["vendor", "--from", str(tmp_path / "nope")])
    captured = capsys.readouterr()
    assert code == 1
    assert "source tree not found" in captured.err


def test_vendor_noop_preserves_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # capture the real source tree before patching the lexicon root.
    source = cli._LEXICON_ROOT / "pub" / "layers"
    lexicons = tmp_path / "lexicons"
    lexicons.mkdir()
    _seed_lexicon_root(lexicons)
    monkeypatch.setattr(cli, "_LEXICON_ROOT", lexicons)
    before = load_manifest(lexicons / cli._MANIFEST_NAME)
    # vendor from the very tree already vendored: content is identical, so the
    # hash and vendoring date must be preserved (keeps gen --check stable).
    code = cli.main(["vendor", "--from", str(source)])
    captured = capsys.readouterr()
    assert code == 0
    after = load_manifest(lexicons / cli._MANIFEST_NAME)
    assert after.lexicon_tree_hash == before.lexicon_tree_hash
    assert after.vendored_at == before.vendored_at
    assert after.lexicon_files == before.lexicon_files
    assert after.record_types == before.record_types
    assert "vendored" in captured.out


def test_vendor_changed_tree_recomputes_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lexicons = tmp_path / "lexicons"
    lexicons.mkdir()
    _seed_lexicon_root(lexicons)
    monkeypatch.setattr(cli, "_LEXICON_ROOT", lexicons)
    before = load_manifest(lexicons / cli._MANIFEST_NAME)
    # build a modified source tree: add one lexicon file so the content differs.
    source = tmp_path / "source"
    shutil.copytree(cli._LEXICON_ROOT / "pub" / "layers", source)
    (source / "extra.json").write_text('{"id": "pub.layers.extra"}', encoding="utf-8")
    code = cli.main(
        [
            "vendor",
            "--from",
            str(source),
            "--layers-version",
            "9.9.9",
            "--vendored-at",
            "2030-01-01",
        ],
    )
    assert code == 0
    after = load_manifest(lexicons / cli._MANIFEST_NAME)
    assert after.lexicon_tree_hash != before.lexicon_tree_hash
    assert after.layers_version == "9.9.9"
    assert after.vendored_at == "2030-01-01"
    assert after.lexicon_files == before.lexicon_files + 1


# pull -----------------------------------------------------------------------


def test_pull_stages_and_commits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # mock the network-backed pull so no PDS is contacted; the fake stages one
    # record into the repository, exercising the commit path without a network.
    calls: dict[str, str] = {}

    def fake_pull(did: str, *, endpoint: str, into: Repository) -> Repository:
        calls["did"] = did
        calls["endpoint"] = endpoint
        into.save(
            "at://did:plc:example/pub.layers.persona.persona/a",
            persona_records.Persona(createdAt=_NOW, name="pulled"),
        )
        return into

    monkeypatch.setattr("lairs.author.publish.pull", fake_pull)
    repo_dir = tmp_path / "repo"
    code = cli.main(
        [
            "pull",
            "did:plc:example",
            "--endpoint",
            "https://pds.example",
            "--into",
            str(repo_dir),
        ],
    )
    captured = capsys.readouterr()
    assert code == 0
    assert calls == {"did": "did:plc:example", "endpoint": "https://pds.example"}
    assert "pulled 1 record(s)" in captured.out
    assert "committed snapshot" in captured.out


def test_pull_with_no_records_skips_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_pull(_did: str, *, endpoint: str, into: Repository) -> Repository:  # noqa: ARG001
        return into

    monkeypatch.setattr("lairs.author.publish.pull", fake_pull)
    code = cli.main(
        [
            "pull",
            "did:plc:empty",
            "--endpoint",
            "https://pds.example",
            "--into",
            str(tmp_path / "repo"),
        ],
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "nothing to commit" in captured.out


# publish --------------------------------------------------------------------


def _make_repo(path: Path) -> Repository:
    """Initialise a Repository with one committed record for publish tests."""
    repo = Repository.init(path)
    persona = persona_records.Persona(createdAt=_NOW, name="tester")
    repo.save("at://did:plc:me/pub.layers.persona.persona/a", persona)
    repo.commit("seed")
    return repo


def test_publish_defaults_to_dry_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_dir = tmp_path / "repo"
    _make_repo(repo_dir)
    code = cli.main(
        [
            "publish",
            "--repo",
            str(repo_dir),
            "--to",
            "did:plc:me",
        ],
    )
    captured = capsys.readouterr()
    assert code == 0
    # with no endpoint the diff is against an empty PDS, so every staged record
    # is planned as a create and nothing is written.
    assert "publish plan (planned)" in captured.out
    assert "creates: 1" in captured.out
    assert "dry run" in captured.out


def test_publish_yes_without_endpoint_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_dir = tmp_path / "repo"
    _make_repo(repo_dir)
    code = cli.main(
        [
            "publish",
            "--repo",
            str(repo_dir),
            "--to",
            "did:plc:me",
            "--yes",
        ],
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "requires --endpoint" in captured.err


# materialize / inspect ------------------------------------------------------


def test_materialize_loads_and_writes_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = Corpus.new()
    corpus.add_expression(
        "at://did:plc:me/pub.layers.expression.expression/x",
        expression_records.Expression(
            createdAt=_NOW,
            id="x",
            kind="text",
            text="hello world",
        ),
    )

    def fake_load(
        uri: str,
        *,
        source: str = "auto",
        pds_client: PdsClient | None = None,
        follow_refs: bool = True,
    ) -> Corpus:
        assert uri == "at://did:plc:me/pub.layers.corpus.corpus/c"
        assert source == "pds"
        assert pds_client is not None
        # the CLI defaults to following refs across accounts.
        assert follow_refs is True
        return corpus

    monkeypatch.setattr("lairs.data.load_corpus", fake_load)
    out = tmp_path / "views"
    code = cli.main(
        [
            "materialize",
            "at://did:plc:me/pub.layers.corpus.corpus/c",
            "--endpoint",
            "https://pds.example",
            "--out",
            str(out),
        ],
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "materialized" in captured.out
    assert (out / "expressions.parquet").exists()


def test_inspect_prints_per_type_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = Corpus.new()
    corpus.add_expression(
        "at://did:plc:me/pub.layers.expression.expression/x",
        expression_records.Expression(createdAt=_NOW, id="x", kind="text", text="a"),
    )
    corpus.add_record(
        "at://did:plc:me/pub.layers.media.media/m",
        media_records.Media(createdAt=_NOW, kind="text"),
    )

    def fake_load(
        _uri: str,
        *,
        source: str = "auto",
        pds_client: PdsClient | None = None,
        follow_refs: bool = True,
    ) -> Corpus:
        assert source == "pds"
        assert pds_client is not None
        assert follow_refs is True
        return corpus

    monkeypatch.setattr("lairs.data.load_corpus", fake_load)
    code = cli.main(
        [
            "inspect",
            "at://did:plc:me/pub.layers.corpus.corpus/c",
            "--endpoint",
            "https://pds.example",
        ],
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "2 record(s)" in captured.out
    assert "pub.layers.expression.expression: 1" in captured.out
    assert "pub.layers.media.media: 1" in captured.out


# nsid helper ----------------------------------------------------------------


def test_nsid_of_extracts_collection() -> None:
    assert cli._nsid_of("at://did:plc:me/pub.layers.media.media/abc") == (
        "pub.layers.media.media"
    )
    assert cli._nsid_of("not-an-at-uri") == ""


@pytest.mark.integration
def test_cli_toc_against_live_pds(
    pds_server: PdsServer,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # drive `lairs toc` end-to-end against the dockerized PDS: seed a corpus
    # record, then run the command and assert it lists the collection.
    httpx.post(
        f"{pds_server.endpoint}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {pds_server.access_jwt}"},
        json={
            "repo": pds_server.did,
            "collection": "pub.layers.corpus.corpus",
            "record": {
                "$type": "pub.layers.corpus.corpus",
                "name": "cli live corpus",
                "createdAt": "2026-06-18T00:00:00Z",
            },
        },
        timeout=30.0,
    ).raise_for_status()
    code = cli.main(
        ["toc", pds_server.did, "--endpoint", pds_server.endpoint, "--source", "pds"],
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "pub.layers.corpus.corpus" in captured.out


def _raise_value_error(actor: str, **kwargs: str | None) -> tuple[()]:
    _ = (actor, kwargs)
    msg = "bad source"
    raise ValueError(msg)


def test_print_datasets_table(capsys: pytest.CaptureFixture[str]) -> None:
    rows = (
        DatasetSummary(
            uri="at://did:plc:x/pub.layers.corpus.corpus/a",
            did="did:plc:x",
            name="demo corpus",
            domain="biomedical",
            language="en",
            expression_count=10,
        ),
    )
    cli._print_datasets(rows, as_json=False)
    out = capsys.readouterr().out
    assert "demo corpus" in out
    assert "biomedical" in out
    assert "at://did:plc:x/pub.layers.corpus.corpus/a" in out


def test_print_datasets_empty(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_datasets((), as_json=False)
    assert "no datasets found" in capsys.readouterr().out


def test_print_datasets_json(capsys: pytest.CaptureFixture[str]) -> None:
    rows = (DatasetSummary(uri="at://x", did="did:plc:x", name="demo"),)
    cli._print_datasets(rows, as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["name"] == "demo"


def test_print_toc(capsys: pytest.CaptureFixture[str]) -> None:
    toc = RepoTableOfContents(
        did="did:plc:x",
        handle="alice.test",
        collections=(
            CollectionCount(nsid="pub.layers.corpus.corpus", is_dataset_like=True),
            CollectionCount(nsid="app.bsky.feed.post"),
        ),
        dataset_collections=("pub.layers.corpus.corpus",),
    )
    cli._print_toc(toc, as_json=False)
    out = capsys.readouterr().out
    assert "alice.test" in out
    assert "pub.layers.corpus.corpus" in out


def test_datasets_reports_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(discovery, "list_datasets", _raise_value_error)
    code = cli.main(["datasets", "did:plc:x"])
    assert code == 1
    assert "error: bad source" in capsys.readouterr().err


def test_search_prints_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_discover(
        actors: list[str],
        **kwargs: str | None,
    ) -> tuple[DatasetSummary, ...]:
        _ = (actors, kwargs)
        return (
            DatasetSummary(
                uri="at://did:plc:x/pub.layers.corpus.corpus/a",
                did="did:plc:x",
                name="demo corpus",
            ),
        )

    monkeypatch.setattr(discovery, "discover_datasets", fake_discover)
    code = cli.main(["search", "did:plc:x", "did:plc:y"])
    out = capsys.readouterr().out
    assert code == 0
    assert "demo corpus" in out


def test_print_report(capsys: pytest.CaptureFixture[str]) -> None:
    report = CrawlReport(
        repos_seen=3,
        repos_with_corpora=2,
        cards_built=5,
        skipped=("did:plc:z: no pub.layers.corpus.corpus",),
        revision="abcd",
    )
    cli._print_report(report)
    out = capsys.readouterr().out
    assert "repos seen: 3" in out
    assert "cards built: 5" in out
    assert "skipped did:plc:z" in out
    assert "committed abcd" in out


def test_print_card_diff(capsys: pytest.CaptureFixture[str]) -> None:
    diff = CardDiff(added=("at://a",), changed=("at://b",), removed=())
    cli._print_card_diff(diff)
    out = capsys.readouterr().out
    assert "added: 1" in out
    assert "+ at://a" in out
    assert "~ at://b" in out


def _seed_corpus_record(server: PdsServer, name: str) -> None:
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {server.access_jwt}"},
        json={
            "repo": server.did,
            "collection": "pub.layers.corpus.corpus",
            "record": {
                "$type": "pub.layers.corpus.corpus",
                "name": name,
                "createdAt": "2026-06-18T00:00:00Z",
            },
        },
        timeout=30.0,
    )
    response.raise_for_status()


@pytest.mark.integration
def test_index_build_and_search_live(
    pds_server: PdsServer,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_corpus_record(pds_server, "cli indexed corpus")
    index_dir = tmp_path / "idx"
    build_code = cli.main(
        [
            "index",
            "build",
            "--into",
            str(index_dir),
            "--endpoint",
            pds_server.endpoint,
            "--seed-did",
            pds_server.did,
        ],
    )
    assert build_code == 0
    search_code = cli.main(["index", "search", "--index", str(index_dir), "corpus"])
    out = capsys.readouterr().out
    assert search_code == 0
    assert "cli indexed corpus" in out


# index group (fast, monkeypatched) ------------------------------------------


def _make_search_hit(name: str, *, domain: str = "biomedical") -> SearchHit:
    """Build a real SearchHit wrapping a real DatasetCard for handler tests."""
    summary = DatasetSummary(
        uri="at://did:plc:x/pub.layers.corpus.corpus/a",
        did="did:plc:x",
        name=name,
        domain=domain,
        language="en",
        expression_count=10,
    )
    card = DatasetCard(
        summary=summary,
        provenance=CardProvenance(
            source_did="did:plc:x",
            source_endpoint="https://pds.example",
            discovered_via="crawl",
        ),
        freshness=CardFreshness(first_seen_at=_NOW, last_updated_at=_NOW),
    )
    return SearchHit(card=card, score=2.5)


class _FakeIndex:
    """A stand-in DiscoveryIndex that records construction and calls."""

    last_init: Path | None = None
    last_open: Path | None = None
    cards_value: tuple[DatasetCard, ...] = ()
    diff_value: CardDiff = CardDiff(added=(), changed=(), removed=())

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def init(cls, path: Path) -> _FakeIndex:
        cls.last_init = path
        return cls(path)

    @classmethod
    def open(cls, path: Path) -> _FakeIndex:
        cls.last_open = path
        return cls(path)

    def cards(self) -> tuple[DatasetCard, ...]:
        return type(self).cards_value

    def diff_cards(self, base: str, head: str) -> CardDiff:
        type(self).diff_value = CardDiff(
            added=(f"{base}->{head}",),
            changed=(),
            removed=(),
        )
        return type(self).diff_value


class _FakeBuildClient:
    """A context-managed PdsClient stand-in for the index build path."""

    def __init__(self, endpoint: str | None) -> None:
        self.endpoint = endpoint

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def list_repos(self) -> list[str]:
        return ["did:plc:auto"]


def test_index_build_reports_crawl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_build_index(
        _index: object,
        dids: object,
        **kwargs: object,
    ) -> CrawlReport:
        captured_kwargs["dids"] = dids
        captured_kwargs.update(kwargs)
        return CrawlReport(repos_seen=1, repos_with_corpora=1, cards_built=1)

    monkeypatch.setattr(cli.discovery, "DiscoveryIndex", _FakeIndex)
    monkeypatch.setattr(cli.discovery, "build_index", fake_build_index)
    monkeypatch.setattr(cli, "PdsClient", _FakeBuildClient)
    code = cli.main(
        [
            "index",
            "build",
            "--into",
            str(tmp_path / "idx"),
            "--endpoint",
            "https://pds.example",
            "--seed-did",
            "did:plc:seed",
        ],
    )
    assert code == 0
    assert _FakeIndex.last_init == tmp_path / "idx"
    assert captured_kwargs["dids"] == ["did:plc:seed"]
    assert captured_kwargs["endpoint"] == "https://pds.example"
    assert "cards built: 1" in capsys.readouterr().out


def test_index_build_reports_http_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_build_index(*_args: object, **_kwargs: object) -> CrawlReport:
        msg = "relay down"
        raise httpx.ConnectError(msg)

    monkeypatch.setattr(cli.discovery, "DiscoveryIndex", _FakeIndex)
    monkeypatch.setattr(cli.discovery, "build_index", fake_build_index)
    monkeypatch.setattr(cli, "PdsClient", _FakeBuildClient)
    code = cli.main(
        [
            "index",
            "build",
            "--into",
            str(tmp_path / "idx"),
            "--endpoint",
            "https://pds.example",
        ],
    )
    assert code == 1
    assert "error: relay down" in capsys.readouterr().err


def test_index_update_reports_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    def fake_update_index(
        _index: object,
        relay: str,
        *,
        limit: int | None = None,
    ) -> CrawlReport:
        seen["relay"] = relay
        seen["limit"] = limit
        return CrawlReport(repos_seen=2, repos_with_corpora=2, cards_built=2)

    monkeypatch.setattr(cli.discovery, "DiscoveryIndex", _FakeIndex)
    monkeypatch.setattr(cli.discovery, "update_index", fake_update_index)
    code = cli.main(
        [
            "index",
            "update",
            "--index",
            str(tmp_path / "idx"),
            "--relay",
            "wss://relay.example",
            "--limit",
            "5",
        ],
    )
    assert code == 0
    assert _FakeIndex.last_open == tmp_path / "idx"
    assert seen == {"relay": "wss://relay.example", "limit": 5}
    assert "cards built: 2" in capsys.readouterr().out


def test_index_update_reports_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_update_index(*_args: object, **_kwargs: object) -> CrawlReport:
        msg = "no cursor"
        raise RuntimeError(msg)

    monkeypatch.setattr(cli.discovery, "DiscoveryIndex", _FakeIndex)
    monkeypatch.setattr(cli.discovery, "update_index", fake_update_index)
    code = cli.main(
        ["index", "update", "--index", str(tmp_path / "idx"), "--relay", "wss://r"],
    )
    assert code == 1
    assert "error: no cursor" in capsys.readouterr().err


def test_index_search_builds_query_and_prints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, SearchQuery] = {}

    def fake_search(cards: object, query: SearchQuery) -> list[SearchHit]:
        _ = cards
        captured["query"] = query
        return [_make_search_hit("biomed corpus")]

    monkeypatch.setattr(cli.discovery, "DiscoveryIndex", _FakeIndex)
    monkeypatch.setattr(cli.discovery, "search", fake_search)
    code = cli.main(
        [
            "index",
            "search",
            "--index",
            str(tmp_path / "idx"),
            "biomed",
            "--domain",
            "biomedical",
            "--language",
            "en",
            "--min-expressions",
            "3",
            "--min-rounds",
            "2",
        ],
    )
    out = capsys.readouterr().out
    assert code == 0
    query = captured["query"]
    assert query.text == "biomed"
    assert query.domain == "biomedical"
    assert query.language == "en"
    assert query.min_expressions == 3
    assert query.min_annotation_rounds == 2
    assert "biomed corpus" in out


def test_index_search_duckdb_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    accel_calls: dict[str, object] = {}

    def fake_accelerated(
        index: object,
        query: SearchQuery,
        *,
        out_dir: Path,
    ) -> list[SearchHit]:
        _ = (index, query)
        accel_calls["out_dir"] = out_dir
        return [_make_search_hit("accelerated corpus")]

    def fail_search(*_args: object, **_kwargs: object) -> list[SearchHit]:
        msg = "the in-memory search must not run on the duckdb branch"
        raise AssertionError(msg)

    index_dir = tmp_path / "idx"
    monkeypatch.setattr(cli.discovery, "DiscoveryIndex", _FakeIndex)
    monkeypatch.setattr(cli.discovery, "search", fail_search)
    monkeypatch.setattr(cli.accelerator, "search_accelerated", fake_accelerated)
    code = cli.main(
        ["index", "search", "--index", str(index_dir), "x", "--duckdb"],
    )
    out = capsys.readouterr().out
    assert code == 0
    assert accel_calls["out_dir"] == index_dir / ".accel"
    assert "accelerated corpus" in out


def test_index_diff_prints_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli.discovery, "DiscoveryIndex", _FakeIndex)
    code = cli.main(
        ["index", "diff", "--index", str(tmp_path / "idx"), "rev-a", "rev-b"],
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "added: 1" in out
    assert "+ rev-a->rev-b" in out


# toc (fast, monkeypatched) --------------------------------------------------


def test_toc_prints_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    def fake_toc(
        actor: str,
        *,
        source: str = "auto",
        counts: bool = False,
        pds_client: PdsClient | None = None,
    ) -> RepoTableOfContents:
        seen["actor"] = actor
        seen["source"] = source
        seen["counts"] = counts
        seen["pds_client_is_none"] = pds_client is None
        return RepoTableOfContents(
            did="did:plc:x",
            handle="alice.test",
            collections=(
                CollectionCount(
                    nsid="pub.layers.corpus.corpus",
                    is_dataset_like=True,
                    count=4,
                ),
            ),
            dataset_collections=("pub.layers.corpus.corpus",),
        )

    monkeypatch.setattr(cli.discovery, "table_of_contents", fake_toc)
    code = cli.main(["toc", "alice.test", "--source", "pds", "--counts"])
    out = capsys.readouterr().out
    assert code == 0
    assert seen == {
        "actor": "alice.test",
        "source": "pds",
        "counts": True,
        "pds_client_is_none": True,
    }
    assert "alice.test" in out
    assert "pub.layers.corpus.corpus" in out


def test_toc_json_branch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_toc(actor: str, **_kwargs: object) -> RepoTableOfContents:
        _ = actor
        return RepoTableOfContents(
            did="did:plc:x",
            handle="alice.test",
            collections=(),
            dataset_collections=(),
        )

    monkeypatch.setattr(cli.discovery, "table_of_contents", fake_toc)
    code = cli.main(["toc", "alice.test", "--json"])
    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["did"] == "did:plc:x"


def test_toc_reports_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_toc(actor: str, **_kwargs: object) -> RepoTableOfContents:
        _ = actor
        msg = "unknown source"
        raise ValueError(msg)

    monkeypatch.setattr(cli.discovery, "table_of_contents", fake_toc)
    code = cli.main(["toc", "alice.test"])
    assert code == 1
    assert "error: unknown source" in capsys.readouterr().err


# materialize / inspect error paths ------------------------------------------


def test_materialize_reports_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load(_uri: str, **_kwargs: object) -> Corpus:
        msg = "could not resolve actor"
        raise IdentityError(msg)

    monkeypatch.setattr("lairs.data.load_corpus", fake_load)
    code = cli.main(
        [
            "materialize",
            "at://did:plc:me/pub.layers.corpus.corpus/c",
            "--endpoint",
            "https://pds.example",
            "--out",
            str(tmp_path / "views"),
        ],
    )
    assert code == 1
    assert "error: could not resolve actor" in capsys.readouterr().err


def test_inspect_reports_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load(_uri: str, **_kwargs: object) -> Corpus:
        msg = "pds unreachable"
        raise httpx.ConnectError(msg)

    monkeypatch.setattr("lairs.data.load_corpus", fake_load)
    code = cli.main(
        [
            "inspect",
            "at://did:plc:me/pub.layers.corpus.corpus/c",
            "--endpoint",
            "https://pds.example",
        ],
    )
    assert code == 1
    assert "error: pds unreachable" in capsys.readouterr().err


# tui (fast, monkeypatched) --------------------------------------------------


def test_tui_delegates_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str | None] = {}

    def fake_run_tui(
        *,
        index_path: str | None = None,
        data_path: str | None = None,
        repo_path: str | None = None,
    ) -> None:
        seen["index_path"] = index_path
        seen["data_path"] = data_path
        seen["repo_path"] = repo_path

    monkeypatch.setattr(cli, "run_tui", fake_run_tui)
    code = cli.main(
        [
            "tui",
            "--index",
            "idx-dir",
            "--repo",
            "repo-dir",
            "--data",
            "data-dir",
        ],
    )
    assert code == 0
    assert seen == {
        "index_path": "idx-dir",
        "data_path": "data-dir",
        "repo_path": "repo-dir",
    }


# login / logout / whoami ----------------------------------------------------

_FAKE_SESSION = Session(
    did="did:plc:me",
    pds_endpoint="https://pds.example",
    access_jwt="access",
    refresh_jwt="refresh",
    handle="me.test",
    password="app-pw",
)


def _fake_login(identifier: str, password: str, *, pds: str | None = None) -> Session:
    _ = (identifier, password, pds)
    return _FAKE_SESSION


def test_login_saves_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(auth, "login", _fake_login)
    code = cli.main(["login", "me.test", "--app-password", "app-pw"])
    out = capsys.readouterr().out
    assert code == 0
    assert "logged in as me.test (did:plc:me)" in out
    assert auth.SessionStore().load() == _FAKE_SESSION


def test_login_reads_env_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LAIRS_APP_PASSWORD", "app-pw")
    monkeypatch.setattr(auth, "login", _fake_login)
    code = cli.main(["login", "me.test"])
    assert code == 0
    assert "logged in" in capsys.readouterr().out


def test_login_requires_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LAIRS_APP_PASSWORD", raising=False)
    code = cli.main(["login", "me.test"])
    assert code == 1
    assert "LAIRS_APP_PASSWORD" in capsys.readouterr().err


def test_whoami_not_logged_in(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["whoami"])
    assert code == 1
    assert "not logged in" in capsys.readouterr().out


def test_whoami_after_login(capsys: pytest.CaptureFixture[str]) -> None:
    auth.SessionStore().save(_FAKE_SESSION)
    code = cli.main(["whoami"])
    out = capsys.readouterr().out
    assert code == 0
    assert "me.test" in out
    assert "did:plc:me" in out


def test_logout_deletes_session(capsys: pytest.CaptureFixture[str]) -> None:
    auth.SessionStore().save(_FAKE_SESSION)
    code = cli.main(["logout"])
    assert code == 0
    assert "logged out" in capsys.readouterr().out
    assert auth.SessionStore().load() is None


def test_logout_when_not_logged_in(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["logout"])
    assert code == 0
    assert "not logged in" in capsys.readouterr().out


def _fake_publish(  # noqa: PLR0913  (mirrors the publish() signature)
    repo: Repository,
    revision: str,
    *,
    to: str,
    endpoint: str | None = None,
    client: httpx.Client | None = None,
    dry_run: bool = False,
) -> PublishPlan:
    _ = repo
    _PUBLISH_CALLS.append((to, endpoint, dry_run, client is None))
    return PublishPlan(repo=to, revision=revision, creates=(), updates=(), deletes=())


_PUBLISH_CALLS: list[tuple[str, str | None, bool, bool]] = []


def test_publish_uses_session_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _PUBLISH_CALLS.clear()
    auth.SessionStore().save(_FAKE_SESSION)
    monkeypatch.setattr("lairs.author.publish.publish", _fake_publish)
    repo_dir = tmp_path / "repo"
    _make_repo(repo_dir)
    code = cli.main(["publish", "--repo", str(repo_dir)])
    assert code == 0
    target, endpoint, dry_run, client_is_none = _PUBLISH_CALLS[0]
    assert target == "did:plc:me"
    assert endpoint == "https://pds.example"
    assert dry_run is True
    assert client_is_none is True


def test_publish_yes_injects_authed_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _PUBLISH_CALLS.clear()
    auth.SessionStore().save(_FAKE_SESSION)
    monkeypatch.setattr("lairs.author.publish.publish", _fake_publish)
    repo_dir = tmp_path / "repo"
    _make_repo(repo_dir)
    code = cli.main(["publish", "--repo", str(repo_dir), "--yes"])
    assert code == 0
    assert "applied" in capsys.readouterr().out
    _target, _endpoint, dry_run, client_is_none = _PUBLISH_CALLS[0]
    assert dry_run is False
    assert client_is_none is False  # an authenticated client was injected


@pytest.mark.integration
def test_login_and_publish_live(
    pds_server: PdsServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # mint an app password, log in via the CLI, then apply a real publish and
    # confirm the record landed on the PDS.
    minted = httpx.post(
        f"{pds_server.endpoint}/xrpc/com.atproto.server.createAppPassword",
        headers={"Authorization": f"Bearer {pds_server.access_jwt}"},
        json={"name": "cli-publish-test"},
        timeout=30.0,
    )
    minted.raise_for_status()
    monkeypatch.setenv("LAIRS_APP_PASSWORD", str(minted.json()["password"]))
    assert cli.main(["login", pds_server.handle, "--pds", pds_server.endpoint]) == 0

    repo_dir = tmp_path / "repo"
    repo = Repository.init(repo_dir)
    uri = f"at://{pds_server.did}/pub.layers.expression.expression/cliauth"
    repo.save(
        uri,
        expression_records.Expression(
            id="00000000-0000-0000-0000-000000000001",
            text="published via cli",
            kind="sentence",
            createdAt=_NOW,
        ),
    )
    repo.commit("seed")
    code = cli.main(["publish", "--repo", str(repo_dir), "--yes"])
    out = capsys.readouterr().out
    assert code == 0
    assert "applied" in out

    fetched = httpx.get(
        f"{pds_server.endpoint}/xrpc/com.atproto.repo.getRecord",
        params={
            "repo": pds_server.did,
            "collection": "pub.layers.expression.expression",
            "rkey": "cliauth",
        },
        timeout=30.0,
    )
    assert fetched.status_code == 200
    assert fetched.json()["value"]["text"] == "published via cli"
