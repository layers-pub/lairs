# API reference

Per-symbol documentation generated from the source docstrings. Use this
when you know what you want to call and need the exact signature,
parameter list, raised exceptions, and return type. For task-oriented
walk-throughs see the [guides](../guide/index.md). For design rationale
see the [concepts](../concepts/index.md).

## Records and data

- [Records](records.md): `BlobRef`, the view helpers, and the generated
  `pub.layers.*` record namespaces.
- [Shared types](types.md): the `JsonValue` alias and the type variables.

## ATProto access

- [ATProto access](atproto.md): identity resolution, the PDS and appview
  record clients, blob fetch, and the firehose surface.

## Store

- [Store](store.md): the in-memory pool, the schematic Repository, the
  Arrow views, and the blob cache.

## Media

- [Media](media.md): media resolution, anchor resolution, and the audio,
  video, and neural decode and slicing helpers.

## Code generation

- [Code generation](codegen.md): the lexicon-to-model pipeline, the
  schema-to-spec mapping, the emitter, and the vendoring manifest.
