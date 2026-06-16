# Vendored Layers lexicons

This directory holds the `pub.layers.*` lexicon JSON, vendored verbatim from
[layers-pub](https://github.com/layers-pub) (`layers/lexicons/pub/layers/`).
The lexicons are the single source of truth for every `lairs` record model.

- The tree is a mechanical, reviewable copy; nothing here is hand-edited.
- `MANIFEST.toml` records the provenance (Layers git sha, version, vendor
  timestamp, and a content hash of the tree).
- `lairs vendor --layers-ref <git-sha|tag>` refreshes the tree and rewrites the
  manifest.
- `lairs gen` regenerates the committed models under
  `lairs/records/_generated/` from this tree; `lairs gen --check` is the CI
  drift gate.

This scaffold ships the directory empty; the lexicon JSON is added by the first
`lairs vendor` run.
