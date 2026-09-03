<h1 align="center">lairs</h1>

<p align="center">
  <em>A read/write dataset client for the Layers format, built on didactic.</em>
</p>

<p align="center">
  <a href="https://github.com/layers-pub/lairs/actions/workflows/ci.yml"><img src="https://github.com/layers-pub/lairs/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://layers.pub/lairs/"><img src="https://img.shields.io/badge/docs-online-blue" alt="Docs"></a>
  <a href="https://pypi.org/project/lairs/"><img src="https://img.shields.io/pypi/v/lairs" alt="PyPI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.14%2B-blue" alt="Python 3.14+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://layers.pub/lairs/tutorial/"><strong>Tutorial</strong></a>
  ·
  <a href="https://layers.pub/lairs/guide/"><strong>Guides</strong></a>
  ·
  <a href="https://layers.pub/lairs/concepts/"><strong>Concepts</strong></a>
  ·
  <a href="https://layers.pub/lairs/reference/"><strong>API</strong></a>
  ·
  <a href="https://layers.pub/lairs/development/"><strong>Development</strong></a>
</p>

---

`lairs` is a Python client for reading and writing data in the
[Layers](https://github.com/layers-pub) format. It downloads `pub.layers.*`
records from ATProto Personal Data Servers, validates them against models
generated from the Layers lexicons, holds them in memory or in a local
content-addressed store, and exposes them through a `datasets`-like API with
tooling for the modalities Layers relates: audio, video, and time-series
signals. On the write side it constructs records, uploads media blobs, and
publishes records in bulk to the authenticated user's own repository, with the
local store doubling as schema-aware version control.

`lairs` is built on [didactic](https://github.com/panproto/didactic), which is
built on [panproto](https://github.com/panproto/phrom). Structured values
in `lairs` are `didactic` models built programmatically from the `pub.layers.*`
ATProto lexicons.

## Installation

`lairs` can be installed from pypi:

```bash
pip install lairs                 # core
```

The core install does not include integration dependencies. Each integration is an
optional extra, discovered at runtime through entry points, so importing `lairs`
never imports an integration's dependency.

```bash
pip install "lairs[hf]"           # HuggingFace datasets and Hub
pip install "lairs[torch]"        # PyTorch exporter
pip install "lairs[audio]"        # audio decoding
pip install "lairs[conllu]"       # the CoNLL-U codec
```

## Usage

```python
import lairs
from lairs.atproto import PdsClient

# read a corpus straight from the public Layers PDS
with PdsClient("https://repo.layers.pub") as client:
    corpus = lairs.load_corpus(
        "at://did:plc:myu6umexofclib2tvwn23gsc/pub.layers.corpus.corpus/92cfd1034bcef513c2796962",
        source="pds",
        pds_client=client,
    )

print(len(corpus.expressions))
print(corpus.expressions[0].text)
```

The `lairs` command vendors lexicons, regenerates models, and pulls,
materialises, publishes, and inspects corpora:

```bash
lairs gen --check          # fail if the committed models drift from the lexicons
lairs pull did:plc:abc     # ingest an account's records into a local repository
lairs materialize <uri>    # build Arrow and Parquet views
lairs publish --repo ... --revision v0.1 --to did:plc:abc   # dry-run plan by default
```

## Documentation

The documentation is available at [layers.pub/lairs/](https://layers.pub/lairs/). 
It can be built locally with:

```bash
uv run --group docs mkdocs serve
```

## Development

`lairs` uses `uv` along with `ruff`, `ty`, and `pytest` for development.

```bash
uv sync
uv run ruff format --check lairs tests
uv run ruff check lairs tests
uv run ty check
uv run pytest                    # unit tests only
uv run pytest --run-integration  # include integration tests (docker, network, extras)
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide and the
[Development](https://layers.pub/lairs/development/) section of the
documentation for testing, code generation, and the release process. All
participants are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Changelog

Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

`lairs` is released under the [MIT License](LICENSE).

## Acknowledgments

`lairs` was developed with substantial assistance from Claude Code.