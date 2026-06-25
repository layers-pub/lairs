# Code generation

The `pub.layers.*` record models under `lairs/records/_generated/` are
generated from the vendored Layers lexicons. They are committed to the
repository, but they are never edited by hand: the next regeneration overwrites
any manual change, and the generator preserves detail (descriptions,
optionality, refined value types, integer ranges, `knownValues`, union
discriminators) that a hand-written model would drop.

This page is the contributor's view of the pipeline. The user-facing
walkthrough, with every flag, is [Vendoring and codegen](../guide/codegen.md);
the rationale is [Generated models](../concepts/generated-models.md).

## The pipeline

Two CLI commands own it:

```bash
uv run lairs vendor --from <layers-checkout>/lexicons/pub/layers   # copy lexicons in
uv run lairs gen                                                   # generate models
uv run lairs gen --check                                           # drift gate
```

- `lairs vendor` copies a `lexicons/pub/layers` tree from a local Layers
  checkout into `lairs/lexicons/` and rewrites `MANIFEST.toml`, recording the
  Layers version and a hash of the vendored tree.
- `lairs gen` reads the vendored lexicons and writes the model modules under
  `lairs/records/_generated/`. The generator lives in `lairs/codegen/`.
- `lairs gen --check` regenerates into a scratch location and fails if the
  committed modules differ from what the current lexicons produce.

## Reproducibility and the drift gate

Generation is reproducible. The vendored lexicon tree hash is recorded in
`lairs/lexicons/MANIFEST.toml` and embedded in each generated module, so the
committed models always correspond to an exact, recorded lexicon snapshot. The
currently vendored release is recorded as `layers_version` in the manifest.

`lairs gen --check` is the gate. Run it after any change that could affect
generation (a re-vendor, or a change to `lairs/codegen/`) and before committing.
If it fails, run `lairs gen` and commit the regenerated modules together with
the change that caused them.

## When you touch this

- **Adopting a new Layers version.** Re-vendor from the new lexicon tree,
  regenerate, confirm the drift gate is clean, run the suite, and record the
  bump in `CHANGELOG.md` and `docs/project/stability.md`.
- **Changing the generator.** Edits to `lairs/codegen/` change the shape of
  every generated module. Regenerate, review the diff across
  `lairs/records/_generated/`, and make sure the hand-written code in
  `lairs/records/` (such as `BlobRef` and the blob normalization) still lines up
  with the generated output.

Never hand-edit a file under `lairs/records/_generated/`. If a model comes out
wrong, the fix belongs in the lexicon or in the generator, not in the output.
