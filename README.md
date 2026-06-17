# lairs

`lairs` is a Python client for reading and writing data in the
[Layers](https://github.com/layers-pub) format. It downloads `pub.layers.*`
records from ATProto Personal Data Servers, validates them against models
generated from the Layers lexicons, holds them in memory or in a local
content-addressed store, and exposes them through a `datasets`-like API with
tooling for the modalities Layers carries: audio, video, and time-series
signals. On the write side it constructs records, uploads media blobs, and
publishes records in bulk to the authenticated user's own repository, with the
local store doubling as schema-aware version control.

The mental model: `datasets` and `git` for decentralised linguistic annotation.

`lairs` is built on [didactic](https://github.com/panproto/didactic), which is
built on [panproto](https://github.com/panproto/phrom). Every structured value
in `lairs` is a `didactic` model. The project never uses dataclasses, pydantic,
or ad-hoc classes for its data, and type hints never use `Any` or `object`.

The ATProto lexicons are the single source of truth. The `pub.layers.*` models
are not written by hand. They are generated from the vendored lexicons and
committed to the repository. Updating to a new Layers version is a re-vendor, a
regeneration, and a drift check (`lairs gen --check`).

## Installation

The core install carries no integration dependencies. Each integration is an
optional extra, discovered at runtime through entry points, so importing `lairs`
never imports an integration's dependency.

```bash
pip install lairs                 # core
pip install "lairs[hf]"           # HuggingFace datasets and Hub
pip install "lairs[torch]"        # PyTorch exporter
pip install "lairs[audio]"        # audio decoding
pip install "lairs[conllu]"       # the CoNLL-U codec
```

## Usage

```python
import lairs

corpus = lairs.load_corpus(
    "at://did:plc:abc/pub.layers.corpus.corpus/ud-en",
    source="pds",
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

The documentation follows the [Diátaxis](https://diataxis.fr/) structure: a
tutorial, task-oriented guides, conceptual explanation, and an API reference
rendered from the source docstrings. Build it locally with:

```bash
uv run --group docs mkdocs serve
```

## Development

```bash
uv sync
uv run ruff format --check lairs tests
uv run ruff check lairs tests
uv run ty check
uv run pytest                    # unit tests only
uv run pytest --run-integration  # include integration tests (docker, network, extras)
```

## License

MIT
