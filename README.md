# lairs

`lairs` is a Python library for reading and writing data in the
[Layers](https://github.com/layers-pub) format. It downloads `pub.layers.*`
records from ATProto Personal Data Servers (PDSes), validates them against
models generated from the Layers lexicons, versions them in a local
content-addressed store, and exposes them through a `datasets`-like API with
first-class tooling for audio, video, and neural modalities. On the write side
it provides an ergonomic record-authoring surface and bulk-publishes records to
a user's own PDS.

The mental model: `datasets` + `git` for decentralized linguistic annotation.

`lairs` is built on [didactic](https://github.com/panproto/didactic) (which is
built on [panproto](https://github.com/panproto/phrom)). Every structured value
in `lairs` is a `didactic` model; the project never uses dataclasses, pydantic,
or ad-hoc classes for its data, and type hints never use `Any` or `object`.

didactic is a PEP 420 namespace package whose public API lives at
`didactic.api`, so `lairs` imports it as `import didactic.api as dx` and writes
`class X(dx.Model): ...`.

## Status

Scaffold. Most modules are stubs (`raise NotImplementedError`); a few pure
modules (`lairs._types`, `lairs.records.blobref`, `lairs.integrations.ports`,
`lairs.integrations.registry`) are implemented.

## Development

```bash
uv sync
uv run ruff format --check
uv run ruff check
uv run ty check
uv run pytest                  # unit tests only
uv run pytest --run-integration  # include integration tests
```

## License

MIT
