"""Unit and integration tests for lairs.cli."""

from __future__ import annotations

import datetime
import shutil
from typing import TYPE_CHECKING

import pytest

from lairs import cli
from lairs._codegen.manifest import load_manifest
from lairs.data.corpus import Corpus
from lairs.records._generated import expression as expression_records
from lairs.records._generated import media as media_records
from lairs.records._generated import persona as persona_records
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path

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
    for command in ("vendor", "gen", "pull", "materialize", "publish", "inspect"):
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
    ) -> Corpus:
        assert uri == "at://did:plc:me/pub.layers.corpus.corpus/c"
        assert source == "pds"
        assert pds_client is not None
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
    ) -> Corpus:
        assert source == "pds"
        assert pds_client is not None
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
def test_cli_against_live_pds() -> None:
    pytest.skip("requires a live PDS endpoint and credentials")
