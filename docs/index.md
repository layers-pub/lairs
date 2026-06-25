# lairs

`lairs` is a Python client for reading and writing data in the Layers
format. It downloads `pub.layers.*` records from ATProto Personal Data
Servers, validates them against models generated from the Layers
lexicons, holds them in memory or in a content-addressed store, and
exposes them through a dataset API with tooling for the modalities
Layers carries: audio, video, and time-series signals. On the write
side it constructs records, uploads media blobs, and publishes records
in bulk to the authenticated user's own repository, with the local
store doubling as schema-aware version control.

Every structured value in lairs is a [didactic](https://github.com/panproto/didactic)
model. The `pub.layers.*` record models
are generated from the vendored lexicons and committed to the
repository. Updating to a new Layers version involves a re-vendor, a
regeneration, and a drift check.

```python
import lairs
from lairs.atproto import PdsClient

with PdsClient("https://pds.example") as client:
    corpus = lairs.load_corpus(
        "at://did:plc:abc/pub.layers.corpus.corpus/ud-en",
        source="pds",
        pds_client=client,
    )
expressions = corpus.expressions
print(len(expressions))
print(expressions[0].text)
```

The `pds` source reads directly from a PDS and needs an injected
`pds_client`; endpoint discovery and the `appview` and `auto` sources are
not implemented yet.

## Where to start

The documentation follows the [Diátaxis](https://diataxis.fr/)
structure:

- The [Tutorial](tutorial/index.md) works through reading, materializing,
  and authoring a corpus on a single running example. Read it first if
  you have not used lairs before.
- The [Guides](guide/index.md) are task-oriented. Each one answers a
  question of the form "how do I do X" against a specific subsystem.
- The [Concepts](concepts/index.md) explain the design: why models are
  generated rather than authored, how anchors unify the modalities, what
  reproducibility guarantees the store provides.
- The [API reference](reference/index.md) is the per-symbol detail:
  signatures, parameters, raised exceptions, and return types, rendered
  from the source docstrings.

## Scope

lairs reads from any PDS and writes only to the authenticated user's
own repository, through the standard `com.atproto.repo.*` client APIs.
It is not an appview: it does not maintain a cross-user index or consume
the firehose on behalf of others. Records are validated against the
generated lexicon models in both directions.

## Project status

lairs is pre-1.0. Optional integrations (HuggingFace, PyTorch, format
codecs, knowledge-base connectors, experiment trackers) are not part of
the core install: each is an extra, discovered at runtime through entry
points. Importing `lairs` never imports an integration's dependency.
