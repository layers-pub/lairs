# lairs

`lairs` is a Python client for reading and writing data in the Layers
format. It downloads `pub.layers.*` records from ATProto Personal Data
Servers, validates them against models generated from the Layers
lexicons, and holds them in memory or in a content-addressed store. A
dataset API provides access to the records and to the audio, video, and
time-series signals they describe. For writes, lairs constructs records,
uploads media blobs, and publishes records in bulk to the authenticated
user's own repository. The local store also provides schema-aware version
control.

Every structured value in lairs is a
[didactic](https://github.com/panproto/didactic) model. The `pub.layers.*`
record models are generated from the vendored lexicons and committed to
the repository. Updating to a new Layers version requires re-vendoring
the lexicons, regenerating the models, and running the drift check.

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

The documentation follows the [Diátaxis](https://diataxis.fr/) structure:

- The [Tutorial](tutorial/index.md) works through reading, materializing,
  and authoring a corpus on a single running example. Read it first if
  you have not used lairs before.
- The [Guides](guide/index.md) give task-oriented instructions for each
  subsystem.
- The [Concepts](concepts/index.md) explain the design, including generated
  models, anchors across modalities, and the store's reproducibility
  guarantees.
- The [API reference](reference/index.md) documents signatures, parameters,
  raised exceptions, and return types from the source docstrings.

## Scope

lairs reads from any PDS and writes only to the authenticated user's own
repository through the standard `com.atproto.repo.*` client APIs. It is
not an appview: it neither maintains a cross-user index nor consumes the
firehose on behalf of others. Records are validated against the generated
lexicon models in both directions.

## Project status

lairs is pre-1.0. Optional integrations (HuggingFace, PyTorch, format
codecs, knowledge-base connectors, experiment trackers) are not part of
the core install: each is an extra, discovered at runtime through entry
points. Importing `lairs` never imports an integration's dependency.
