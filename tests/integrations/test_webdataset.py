"""Unit and integration tests for lairs.integrations.webdataset."""

from __future__ import annotations

import json
import sys
import tarfile
from typing import TYPE_CHECKING

import pytest

from lairs.integrations.ports import Exporter
from lairs.integrations.webdataset import (
    WebDatasetExporter,
    WebDatasetSpec,
    _bytes_field,
    _MediaCell,
    _str_field,
)

if TYPE_CHECKING:
    from pathlib import Path

pa = pytest.importorskip("pyarrow")


def _members(path: Path) -> list[str]:
    """Return the sorted member names of a tar shard."""
    with tarfile.open(path, "r") as tar:
        return sorted(tar.getnames())


def _read(path: Path, name: str) -> bytes:
    """Return the bytes of one named member of a tar shard."""
    with tarfile.open(path, "r") as tar:
        member = tar.extractfile(name)
        assert member is not None
        return member.read()


def test_name() -> None:
    assert WebDatasetExporter.name == "webdataset"


def test_binds_to_exporter_port() -> None:
    assert isinstance(WebDatasetExporter(), Exporter)


def test_importing_module_does_not_import_webdataset() -> None:
    # importing the module must never pull the optional library in.
    assert "webdataset" not in sys.modules


def test_export_single_shard(tmp_path: Path) -> None:
    table = pa.table({"id": ["a", "b"], "text": ["one", "two"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), key_column="id")
    shards = WebDatasetExporter().export(table, spec=spec)

    assert shards == [tmp_path / "shard-000000.tar"]
    assert _members(shards[0]) == ["a.json", "b.json"]
    payload = json.loads(_read(shards[0], "a.json"))
    assert payload == {"id": "a", "text": "one"}


def test_export_sharding_splits_rows(tmp_path: Path) -> None:
    table = pa.table({"id": ["a", "b", "c", "d", "e"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), key_column="id", shard_size=2)
    shards = WebDatasetExporter().export(table, spec=spec)

    assert [p.name for p in shards] == [
        "shard-000000.tar",
        "shard-000001.tar",
        "shard-000002.tar",
    ]
    assert _members(shards[0]) == ["a.json", "b.json"]
    assert _members(shards[1]) == ["c.json", "d.json"]
    assert _members(shards[2]) == ["e.json"]


def test_export_default_keys_are_zero_padded(tmp_path: Path) -> None:
    table = pa.table({"text": ["x"] * 12})
    spec = WebDatasetSpec(output_dir=str(tmp_path), shard_size=20)
    shards = WebDatasetExporter().export(table, spec=spec)

    names = _members(shards[0])
    assert names[0] == "00.json"
    assert names[-1] == "11.json"


def test_export_default_spec_uses_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    table = pa.table({"text": ["only"]})
    shards = WebDatasetExporter().export(table)

    # the default output_dir of "." yields a path relative to the cwd.
    assert [str(p) for p in shards] == ["shard-000000.tar"]
    assert shards[0].exists()
    assert (tmp_path / "shard-000000.tar").exists()


def test_export_embeds_raw_media_bytes(tmp_path: Path) -> None:
    table = pa.table(
        {
            "id": ["clip"],
            "audio": [b"RIFF-fake-wav-bytes"],
        }
    )
    spec = WebDatasetSpec(
        output_dir=str(tmp_path),
        key_column="id",
        media_column="audio",
    )
    shards = WebDatasetExporter().export(table, spec=spec)

    # the media column is dropped from the json metadata and embedded as bytes.
    assert _members(shards[0]) == ["clip.bin", "clip.json"]
    assert _read(shards[0], "clip.bin") == b"RIFF-fake-wav-bytes"
    assert json.loads(_read(shards[0], "clip.json")) == {"id": "clip"}


def test_export_resolves_media_record_cell(tmp_path: Path) -> None:
    # a json-shaped media record with inline data and a known mime type.
    record = {
        "cid": "bafy123",
        "mimeType": "audio/wav",
        "data": b"WAVE-bytes",
    }
    table = pa.table(
        {
            "id": pa.array(["s0"], type=pa.string()),
            "media": pa.array([record]),
        }
    )
    spec = WebDatasetSpec(
        output_dir=str(tmp_path),
        key_column="id",
        media_column="media",
    )
    shards = WebDatasetExporter().export(table, spec=spec)

    assert _members(shards[0]) == ["s0.json", "s0.wav"]
    assert _read(shards[0], "s0.wav") == b"WAVE-bytes"


def test_export_skips_empty_media(tmp_path: Path) -> None:
    table = pa.table({"id": ["s0", "s1"], "audio": [b"", b"data"]})
    spec = WebDatasetSpec(
        output_dir=str(tmp_path),
        key_column="id",
        media_column="audio",
    )
    shards = WebDatasetExporter().export(table, spec=spec)

    # the empty cell yields no media member; the populated one does.
    assert _members(shards[0]) == ["s0.json", "s1.bin", "s1.json"]


def test_export_sanitises_keys_with_separators(tmp_path: Path) -> None:
    table = pa.table({"uri": ["at://repo/coll/rkey"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), key_column="uri")
    shards = WebDatasetExporter().export(table, spec=spec)

    assert _members(shards[0]) == ["at:__repo_coll_rkey.json"]


def test_export_rejects_nonpositive_shard_size(tmp_path: Path) -> None:
    table = pa.table({"id": ["a"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), shard_size=0)
    with pytest.raises(ValueError, match="shard_size"):
        WebDatasetExporter().export(table, spec=spec)


def test_export_rejects_missing_key_column(tmp_path: Path) -> None:
    table = pa.table({"id": ["a"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), key_column="absent")
    with pytest.raises(ValueError, match="key_column"):
        WebDatasetExporter().export(table, spec=spec)


def test_export_rejects_missing_media_column(tmp_path: Path) -> None:
    table = pa.table({"id": ["a"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), media_column="absent")
    with pytest.raises(ValueError, match="media_column"):
        WebDatasetExporter().export(table, spec=spec)


def test_extension_for_known_and_unknown() -> None:
    exporter = WebDatasetExporter()
    assert exporter._extension_for("audio/wav") == ".wav"
    assert exporter._extension_for("VIDEO/MP4") == ".mp4"
    assert exporter._extension_for("application/x-weird") == ".bin"


def test_media_cell_from_json_picks_fields() -> None:
    cell = _MediaCell.from_json({"cid": "c", "mime_type": "video/mp4", "data": "hi"})
    assert cell.cid == "c"
    assert cell.mime_type == "video/mp4"
    assert cell.data == b"hi"


def test_str_field_priority() -> None:
    assert _str_field({"a": "x", "b": "y"}, "b", "a") == "y"
    assert _str_field({"a": 1}, "a") is None


def test_bytes_field_encodes_str() -> None:
    assert _bytes_field({"data": "abc"}, "data") == b"abc"
    cell = {"data": b"abc"}
    assert _bytes_field(cell, "data") == b"abc"  # ty: ignore[invalid-argument-type]
    assert _bytes_field({}, "data") == b""


def test_load_without_webdataset_raises(tmp_path: Path) -> None:
    if "webdataset" in sys.modules:
        pytest.skip("webdataset is installed; cannot test the missing-import path")
    table = pa.table({"id": ["a"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), key_column="id")
    shards = WebDatasetExporter().export(table, spec=spec)
    with pytest.raises(ImportError, match="webdataset"):
        WebDatasetExporter().load(shards)


@pytest.mark.integration
def test_load_round_trips_through_webdataset(tmp_path: Path) -> None:
    pytest.importorskip("webdataset")
    table = pa.table({"id": ["a", "b"], "text": ["one", "two"]})
    spec = WebDatasetSpec(output_dir=str(tmp_path), key_column="id")
    shards = WebDatasetExporter().export(table, spec=spec)

    samples = list(WebDatasetExporter().load(shards))
    keys = sorted(sample["__key__"] for sample in samples)
    assert keys == ["a", "b"]
