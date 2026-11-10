"""Benchmark bulk ingestion into the lairs record store.

Each run builds a fresh repository in a temporary directory, stages ``n``
synthetic records through one write path, commits once, reads the snapshot
back with ``content_at``, and prints one JSON line of measurements::

    uv run python benchmarks/store_ingest.py --path raw --records 5000
    uv run python benchmarks/store_ingest.py --path models --records 5000
    uv run python benchmarks/store_ingest.py --path save --records 500
    uv run python benchmarks/store_ingest.py --path raw --records 600000 --profile small

The ``layer`` profile mixes three collections in the proportions of a
Universal Dependencies treebank on Layers: annotation layers of about 10 KB of
JSON with several hundred nodes (most of them null, as a PDS serves them),
segmentations of about 3 KB, and sentence expressions of about 0.5 KB. The ``small``
profile writes records of about 250 bytes, the size of a UniMorph entry.

The ``raw`` path stages PDS-shaped JSON through ``save_many_raw``; the
``models`` path validates the same JSON into the generated models first and
stages them through ``save_many``, so its staging time includes model
validation and dumping; the ``save`` path stages the models one record at a
time through ``save``, the per-record layout. Peak memory is the resident set
high-water mark of the whole process.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.expression import Expression
from lairs.records._generated.segmentation import Segmentation
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lairs._types import JsonValue

_DID = "did:plc:benchmark0000000000000000"
_NULL_ANNOTATION_FIELDS = (
    "arguments",
    "childIds",
    "confidence",
    "headIndex",
    "knowledgeRefs",
    "ontologyTypeRef",
    "parentId",
    "spatial",
    "targetIndex",
    "temporal",
    "text",
    "tokenIndex",
    "value",
)
_NULL_ANCHOR_FIELDS = (
    "boundingBox",
    "externalTarget",
    "pageAnchor",
    "signalSpan",
    "spatialRegion",
    "spatioTemporalAnchor",
    "temporalSpan",
    "textSpan",
    "tokenRefSequence",
)
_LAYER_ANNOTATIONS = 14
_SEGMENT_TOKENS = 30


def _uri(collection: str, index: int) -> str:
    """Return a synthetic AT-URI."""
    return f"at://{_DID}/{collection}/{index:09d}"


def _annotation(index: int, token: int) -> dict[str, JsonValue]:
    """Return one PDS-shaped annotation of a token-tag layer."""
    annotation: dict[str, JsonValue] = dict.fromkeys(_NULL_ANNOTATION_FIELDS)
    anchor: dict[str, JsonValue] = dict.fromkeys(_NULL_ANCHOR_FIELDS)
    anchor["tokenRef"] = {
        "tokenIndex": token,
        "tokenizationId": {"value": f"tok-{index}"},
    }
    annotation.update(
        {
            "uuid": {"value": f"{index:09d}-{token:03d}"},
            "label": ("NOUN", "VERB", "ADJ", "ADP", "DET")[(index + token) % 5],
            "anchor": anchor,
            "features": {
                "entries": [
                    {"key": "Case", "value": "Nom"},
                    {"key": "Number", "value": "Sing"},
                ],
            },
        },
    )
    return annotation


def _layer(index: int) -> dict[str, JsonValue]:
    """Return a PDS-shaped annotation layer of about 10 KB."""
    return {
        "$type": "pub.layers.annotation.annotationLayer",
        "expression": _uri("pub.layers.expression.expression", index),
        "kind": "token-tag",
        "subkind": "pos",
        "createdAt": "2026-11-10T00:00:00.000Z",
        "annotations": [_annotation(index, t) for t in range(_LAYER_ANNOTATIONS)],
        "metadata": None,
        "rank": None,
        "sourceMethod": None,
    }


def _segmentation(index: int) -> dict[str, JsonValue]:
    """Return a PDS-shaped segmentation of about 3 KB."""
    tokens: list[JsonValue] = [
        {
            "tokenIndex": t,
            "text": f"word{t}",
            "textSpan": {"byteStart": t * 6, "byteEnd": t * 6 + 5},
        }
        for t in range(_SEGMENT_TOKENS)
    ]
    return {
        "$type": "pub.layers.segmentation.segmentation",
        "expression": _uri("pub.layers.expression.expression", index),
        "createdAt": "2026-11-10T00:00:00.000Z",
        "tokenizations": [
            {"uuid": {"value": f"tok-{index}"}, "kind": "word", "tokens": tokens},
        ],
    }


def _expression(index: int) -> dict[str, JsonValue]:
    """Return a PDS-shaped sentence expression of about 0.5 KB."""
    text = " ".join(f"word{t}" for t in range(_SEGMENT_TOKENS))
    return {
        "$type": "pub.layers.expression.expression",
        "id": f"sent-{index}",
        "kind": "sentence",
        "text": text,
        "languages": ["tr"],
        "createdAt": "2026-11-10T00:00:00.000Z",
        "features": {"entries": [{"key": "sent_id", "value": f"s{index}"}]},
    }


def _small(index: int) -> dict[str, JsonValue]:
    """Return a record of about 250 bytes, the size of a UniMorph entry."""
    return {
        "$type": "pub.layers.expression.expression",
        "id": f"lemma-{index}",
        "kind": "word",
        "text": f"form{index}",
        "languages": ["fi"],
        "createdAt": "2026-11-10T00:00:00.000Z",
        "features": {
            "entries": [
                {"key": "lemma", "value": f"lemma{index // 40}"},
                {"key": "tags", "value": "N;NOM;SG"},
            ],
        },
    }


_LAYER_MIX = (
    ("pub.layers.expression.expression", _expression),
    ("pub.layers.segmentation.segmentation", _segmentation),
    ("pub.layers.annotation.annotationLayer", _layer),
    ("pub.layers.annotation.annotationLayer", _layer),
    ("pub.layers.annotation.annotationLayer", _layer),
)
_MODELS: dict[str, type[dx.Model]] = {
    "pub.layers.expression.expression": Expression,
    "pub.layers.segmentation.segmentation": Segmentation,
    "pub.layers.annotation.annotationLayer": AnnotationLayer,
}


def raw_records(count: int, profile: str) -> Iterator[tuple[str, JsonValue]]:
    """Yield ``count`` synthetic PDS-shaped records, lazily.

    Parameters
    ----------
    count : int
        The number of records.
    profile : str
        ``"layer"`` or ``"small"``.

    Yields
    ------
    tuple of (str, JsonValue)
        An ``(uri, value)`` pair.
    """
    for index in range(count):
        if profile == "small":
            yield _uri("pub.layers.expression.expression", index), _small(index)
            continue
        collection, build = _LAYER_MIX[index % len(_LAYER_MIX)]
        yield _uri(collection, index), build(index)


def model_records(count: int, profile: str) -> Iterator[tuple[str, dx.Model]]:
    """Yield the records of :func:`raw_records` validated into their models.

    Parameters
    ----------
    count : int
        The number of records.
    profile : str
        ``"layer"`` or ``"small"``.

    Yields
    ------
    tuple of (str, didactic.api.Model)
        An ``(uri, model)`` pair.
    """
    for uri, value in raw_records(count, profile):
        assert isinstance(value, dict)  # noqa: S101
        body = {key: item for key, item in value.items() if key != "$type"}
        model = _MODELS[uri.split("/")[3]]
        yield uri, model.model_validate_json(json.dumps(body))


def _disk(path: Path) -> tuple[int, int]:
    """Return the file count and byte size under ``path``."""
    files = 0
    size = 0
    for root, _, names in os.walk(path):
        for name in names:
            files += 1
            size += (Path(root) / name).stat().st_size
    return files, size


def run(path: str, count: int, profile: str) -> dict[str, JsonValue]:
    """Ingest, commit, and read back ``count`` records; return measurements.

    Parameters
    ----------
    path : str
        ``"raw"``, ``"models"``, or ``"save"``.
    count : int
        The number of records.
    profile : str
        ``"layer"`` or ``"small"``.

    Returns
    -------
    dict
        The measurements.
    """
    with tempfile.TemporaryDirectory() as scratch:
        repo = Repository.init(Path(scratch) / "repo")
        start = time.perf_counter()
        if path == "raw":
            repo.save_many_raw(raw_records(count, profile))
        elif path == "models":
            repo.save_many(model_records(count, profile))
        else:
            for uri, model in model_records(count, profile):
                repo.save(uri, model)
        staged = time.perf_counter()
        revision = repo.commit("benchmark snapshot")
        committed = time.perf_counter()
        content = repo.content_at(revision)
        read = time.perf_counter()
        if len(content) != count:
            msg = f"read back {len(content)} records, expected {count}"
            raise RuntimeError(msg)
        files, size = _disk(repo.path)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macos reports bytes, linux kilobytes.
        peak_mb = peak / 2**20 if sys.platform == "darwin" else peak / 2**10
        return {
            "path": path,
            "profile": profile,
            "records": count,
            "stage_s": round(staged - start, 2),
            "commit_s": round(committed - staged, 2),
            "content_at_s": round(read - committed, 2),
            "records_per_s": round(count / (committed - start)),
            "files": files,
            "mb_on_disk": round(size / 2**20, 1),
            "peak_rss_mb": round(peak_mb),
        }


def main() -> None:
    """Parse arguments, run one benchmark, and print its JSON line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", choices=("raw", "models", "save"), default="raw")
    parser.add_argument("--records", type=int, default=5000)
    parser.add_argument("--profile", choices=("layer", "small"), default="layer")
    args = parser.parse_args()
    result = run(args.path, args.records, args.profile)
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
