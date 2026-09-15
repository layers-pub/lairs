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
"""

from __future__ import annotations

import json
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

import didactic.api as dx

from lairs.store.repository import Repository

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


if __name__ == "__main__":
    sys.stdout.write(json.dumps(build(Path(sys.argv[1])), indent=2, sort_keys=True))
    sys.stdout.write("\n")
