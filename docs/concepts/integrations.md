# Integrations

lairs connects to HuggingFace, PyTorch, linguistic-annotation formats,
and knowledge bases through optional integrations. Each integration is
discovered at runtime and written against a small set of stable surfaces
rather than against lairs internals. The core package thus remains
independent of integration-specific dependencies.

## Four adapter surfaces

An adapter never reaches into lairs internals. It binds to one or more
of four canonical data surfaces, each of which already exists and is
stable:

1. **Records**: the generated `dx.Model` instances, the typed object
   layer.
2. **Arrow views**: the flattened table form with typed anchor columns.
   Most ML exporters consume Arrow rather than bespoke per-framework
   representations.
3. **The anchor resolver**: `resolve_anchor(anchor, target)`, the
   single entry for the text, token, audio, video, or signal slice an
   annotation points at (see [anchors and modality](anchors-and-modality.md)).
4. **Repository revisions**: the version-control commits and tags that
   carry provenance and pin a reproducible dataset version (see
   [reproducibility](reproducibility.md)).

By binding to these surfaces, an adapter rarely needs schema logic of its
own. Layers already normalizes records to (expression text or media) plus
(anchor) plus (annotation kind). A HuggingFace exporter, for instance,
consumes typed columns because the Arrow flattening has already resolved
the polymorphic anchor.

## The three adapter families

Adapters belong to three families, each represented by a small `Protocol`
declared in `lairs.integrations.ports`. Each is generic over its payload
and return types, so no method returns a widened type:

- **Codecs** translate bidirectionally between an external annotation
  format and lairs records. A codec `decode`s an external source into a
  corpus fragment and `encode`s records back out. The pivot is the anchor
  model: a codec only has to translate its spans and labels into lairs
  anchors and one of the seven annotation kinds. lairs owns the rest.
  The registered codecs are CoNLL-U and brat standoff.
- **Exporters** consume the Arrow views (and the anchor resolver) and
  emit a framework-native dataset. An exporter `export`s a view, with an
  optional spec, into a target object such as a `datasets.Dataset` or a
  `torch.utils.data.Dataset`. Examples: HuggingFace `datasets`, PyTorch,
  `tf.data`, WebDataset.
- **Knowledge bases** resolve, entity-link, and expand against external
  knowledge graphs and lexical resources. A connector `resolve`s an
  identifier to an entity, `search`es surface text for candidate
  entities, and optionally returns an entity's `neighbors`. Examples:
  Wikidata, a generic reconciliation endpoint, the `glazing`
  lexical-semantic resources.

A fourth port, `StorageBackend`, abstracts byte storage (read, write,
exists) so the blob cache and the Parquet views can sit on local or
remote storage. It is a supporting surface rather than a fourth adapter
family.

Experiment tracking sits outside these three families.
`lairs.integrations.tracking.log_revision` binds the
Repository-revisions surface to Weights & Biases or MLflow (the
`lairs[tracking]` extra): it records a `ProvenanceBundle` pinning the exact
commit or tag and the vendored lexicon manifest hash, not a copy of the
data. A logged run thus identifies the Repository revision and manifest hash
from which its dataset was derived. Like the adapters, the backend libraries are
imported lazily, so importing the module never pulls in `wandb` or `mlflow`.

The three families correspond to the three places external tools meet
Layers data: at the format boundary (codecs), at the data plane
(exporters), and at the grounding boundary (knowledge bases). The data
surfaces of the previous section and the adapter families of this one are
two different axes: a surface is *what* an adapter touches, a family is
*what kind* of adapter it is. A codec touches the records surface, an
exporter touches the Arrow and anchor surfaces, and a knowledge base
touches the records surface.

## Entry-point discovery

Adapters are not imported by lairs. They are discovered at runtime through
Python entry points, in the groups `lairs.codecs`, `lairs.exporters`, and
`lairs.knowledge_bases`. A registry resolves a name to an adapter class.
It consults in-process registrations first, then (once, lazily) the entry
points. An unknown name raises an error that lists the installed adapters.
In-process registrations take precedence over entry points.

Third parties can thus ship adapters as separate distributions. A
codec in its own PyPI package can register under the same entry-point
group, and lairs needs no change to find it. The registry is generic over
the adapter type it holds, so a lookup returns a precisely typed adapter
class rather than a widened one.

## Why integrations stay out of core

Importing `lairs` never imports an integration's heavy dependency. A
reader who wants records from a PDS need not import `torch`, `datasets`,
or a SPARQL client. Each integration is an optional extra, and its
dependency is loaded only when its adapter is used.

The four stable surfaces also insulate adapters from internal refactors.
The ports are the contract; implementations behind them may change. This
is the same ports-and-adapters discipline used elsewhere in the stack for
emitter and lens frameworks, applied here to integrations.

Uniform codecs and exporters support composed pipelines: decode an
external corpus with a codec, transform it, export it with an exporter,
and mirror it to a hub with its provenance intact. The mirror step uses
the HuggingFace Hub push/pull surface: `push_to_hub`, `load_from_hub`, and
the `dataset_card` and `provenance_bundle` helpers re-exported from
`lairs.integrations.hf`. This surface writes a corpus to the Hub as
Arrow/Parquet shards behind a dataset card carrying the corpus AT-URI,
the Repository revision, and the vendored lexicon manifest hash, and it
reads a mirror back. The PDS and the Repository stay canonical; the Hub
is an export and mirror target. Codecs carry round-trip law fixtures
(`decode(encode(x))` recovers `x` on the supported subset), while
schema-parity fixtures test exporters.

For the stability contract on the ports and the extras, see
[stability](../project/stability.md). For the HuggingFace data path, see the
[exporters guide](../guide/exporters.md#huggingface-hub).
