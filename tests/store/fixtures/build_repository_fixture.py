r"""Build a committed-repository fixture under the installed panproto release.

The fixtures under this directory pin the committed-data carrier of a given
panproto release, so the store's history reads are tested against real
historical repositories rather than against whatever the current release
writes. Each fixture holds the same three-commit history: a record is saved,
updated, and then forgotten, so ``content_at`` can be checked at each revision
including the tombstoned head.

Run this with the panproto and didactic releases you want to pin, from a lairs
checkout whose ``Repository`` write path matches that release, for instance::

    uv run --isolated --no-project --with "panproto==0.72.1" \\
        --with "didactic==0.13.1" --with-editable . \\
        python tests/store/fixtures/build_repository_fixture.py \\
        tests/store/fixtures/panproto-0.72.1-repository

The output directory receives the repository plus a ``fixture.json`` recording
the panproto version and the three commit ids the test reads back.

With ``--packed`` the script instead builds the store layout 2 fixture, whose
three-commit history mixes the per-record and packed layouts: a per-record base,
a packed commit of raw PDS-shaped records and models, and a commit that updates
and forgets packed and per-record records across layouts::

    uv run python tests/store/fixtures/build_repository_fixture.py --packed \\
        tests/store/fixtures/panproto-0.74.3-packed-repository
"""

from __future__ import annotations

import json
import shutil
import sys
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.store.repository import Repository

if TYPE_CHECKING:
    from lairs._types import JsonValue

# the record and values every fixture commits, matched by the test.
FIXTURE_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"
BASE_TEXT = "café"
UPDATED_TEXT = "naïve"


class Expression(dx.Model):
    """The one record type committed into a fixture repository."""

    text: str


def build(target: Path) -> dict[str, str]:
    """Write a three-commit fixture repository at ``target``.

    Parameters
    ----------
    target : pathlib.Path
        The directory to create the repository in. Replaced if it exists.

    Returns
    -------
    dict of str to str
        The fixture metadata written to ``fixture.json``.
    """
    if target.exists():
        shutil.rmtree(target)
    repo = Repository.init(target)
    repo.save(FIXTURE_URI, Expression(text=BASE_TEXT))
    base = repo.commit("base snapshot")
    repo.save(FIXTURE_URI, Expression(text=UPDATED_TEXT))
    updated = repo.commit("updated snapshot")
    repo.forget(FIXTURE_URI)
    deleted = repo.commit("deleted snapshot")
    metadata = {
        "base": base,
        "deleted": deleted,
        "panproto_version": version("panproto"),
        "updated": updated,
        "uri": FIXTURE_URI,
    }
    (target / "fixture.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


# the packed fixture's records. the raw layer carries what a PDS serves and a
# lossless store must keep: the wire ``$type``, explicit nulls, nested empty
# lists, non-ASCII text, an integer beyond 64 bits, floats, and a DAG-JSON link.
PACKED_EXPR_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"
PACKED_KEEP_URI = "at://did:plc:abc/pub.layers.expression.expression/e2"
PACKED_NEW_URI = "at://did:plc:abc/pub.layers.expression.expression/e3"
PACKED_LAYER_URI = "at://did:plc:abc/pub.layers.annotation.annotationLayer/l1"
PACKED_GONE_URI = "at://did:plc:abc/pub.layers.annotation.annotationLayer/l2"
PACKED_LAYER: dict[str, JsonValue] = {
    "$type": "pub.layers.annotation.annotationLayer",
    "kind": "token-tag",
    "metadata": None,
    "annotations": [
        {"label": "NOUN", "childIds": [], "features": {"entries": []}},
        {"label": "VERB", "text": "\u00e7al\u0131\u015ft\u0131", "confidence": None},
    ],
    "rank": 18446744073709551617,
    "scores": [0.1, 1.0, -2.5e-08],
    "source": {"$link": "bafyreigh2akiscaildcqabsyg3dfr6chu3fgpregiymsck7e7aqa4s52zy"},
}
PACKED_GONE: dict[str, JsonValue] = {
    "$type": "pub.layers.annotation.annotationLayer",
    "kind": "span",
    "annotations": [],
}


def build_packed(target: Path) -> dict[str, str]:
    """Write the three-commit store layout 2 fixture repository at ``target``.

    Parameters
    ----------
    target : pathlib.Path
        The directory to create the repository in. Replaced if it exists.

    Returns
    -------
    dict of str to str
        The fixture metadata written to ``fixture.json``.
    """
    if target.exists():
        shutil.rmtree(target)
    repo = Repository.init(target)
    repo.save(PACKED_EXPR_URI, Expression(text=BASE_TEXT))
    repo.save(PACKED_KEEP_URI, Expression(text="keep"))
    base = repo.commit("per-record base")
    repo.save_many_raw(
        [(PACKED_LAYER_URI, PACKED_LAYER), (PACKED_GONE_URI, PACKED_GONE)],
    )
    repo.save_many([(PACKED_NEW_URI, Expression(text="packed"))])
    packed = repo.commit("packed snapshot")
    repo.save_many([(PACKED_EXPR_URI, Expression(text=UPDATED_TEXT))])
    repo.save(PACKED_NEW_URI, Expression(text="per-record over packed"))
    repo.forget(PACKED_GONE_URI)
    mixed = repo.commit("mixed-layout edits")
    metadata = {
        "base": base,
        "mixed": mixed,
        "packed": packed,
        "panproto_version": version("panproto"),
        "store_layout": str(repo.layout_version()),
    }
    (target / "fixture.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


if __name__ == "__main__":
    if sys.argv[1] == "--packed":
        metadata = build_packed(Path(sys.argv[2]))
    else:
        metadata = build(Path(sys.argv[1]))
    sys.stdout.write(json.dumps(metadata, indent=2, sort_keys=True))
    sys.stdout.write("\n")
