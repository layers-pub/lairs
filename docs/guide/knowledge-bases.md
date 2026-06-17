# Knowledge bases: grounding and enrichment

This guide covers the `KnowledgeBase` port and the three bundled connectors:
Wikidata, the generic W3C/OpenRefine reconciliation adapter, and the glazing
lexical-semantic connector. It documents their key, licence, and dependency
requirements, and the explicit errors raised when one is absent.

A knowledge base resolves, entity-links, reconciles, and enriches Layers records
against external graphs and lexical resources. The `KnowledgeBase` protocol in
`lairs.integrations.ports` is three methods, each generic over the model it
returns:

- `resolve(ref)` returns an `Entity` (ref, label, aliases, types, description,
  same_as).
- `search(text, *, lang=None, types=None)` returns a ranked `list[Candidate]`.
- `neighbors(ref, *, rels=None)` returns a `list[Edge]`.

The value models live in `lairs.integrations.kb`. Resolve a connector by name
through the registry:

```python
import lairs

WikidataKB = lairs.knowledge_base("wikidata")
ReconciliationKB = lairs.knowledge_base("reconciliation")
GlazingKB = lairs.knowledge_base("glazing")
```

An unknown name raises `UnknownAdapterError`, listing the available connectors.

## Wikidata

`WikidataKB` connects over Wikidata's public REST, action, and SPARQL endpoints
using `httpx`, a core dependency, so no extra is required for the common path. No
API key or token is needed for the public endpoints.

```python
kb = WikidataKB(lang="en")
entity = kb.resolve("Q42")               # accepts a bare QID or an entity URI
hits = kb.search("Douglas Adams")        # wbsearchentities action API
edges = kb.neighbors("Q42", rels=["P31"])  # SPARQL; all direct statements if rels is None
kb.close()                               # or use it as a context manager
```

`resolve` reads the linked-data EntityData endpoint, and `search` uses the action
API. Type constraints are not expressible in the action API and are ignored by
`search`. Use `ReconciliationKB` against the Wikidata reconciliation endpoint for
type-filtered search. A non-success HTTP response raises `httpx.HTTPStatusError`.

The `lairs[wikidata]` extra (`qwikidata`, `SPARQLWrapper`) is declared for
callers who prefer those clients, but the connector itself talks to the public
endpoints over `httpx` and does not import them. The default transport needs no
extra. Inject an `httpx.Client` to carry a custom user agent or a mock transport.

## Generic reconciliation

`ReconciliationKB` speaks the W3C / OpenRefine reconciliation service API, so one
adapter serves any conforming endpoint (Wikidata, VIAF, Getty, ORCID, and
others). Transport is `httpx`, so no optional extra is required. An endpoint base
URL is mandatory.

```python
kb = ReconciliationKB("https://wikidata.reconci.link/en/api")
candidates = kb.search("Ada Lovelace", types=["Q5"])
entity = kb.resolve("Q7259")
edges = kb.neighbors("Q7259", rels=["P25"])
```

`search` POSTs a `queries` block. `resolve` and `neighbors` use the optional
data-extension service: an endpoint that does not advertise an `extend` service
in its manifest raises `ReconciliationError` with an actionable message
directing the caller to `search` instead, rather than silently returning nothing.
A non-success HTTP response raises `httpx.HTTPStatusError`.

Inject an `httpx.Client` to carry authentication headers when an endpoint
requires them. The connector does not manage credentials itself.

## glazing (lexical-semantic)

`GlazingKB` grounds lemmas, senses, frames, and rolesets against FrameNet,
PropBank, VerbNet, and WordNet through the glazing library, with SemLink-style
cross-reference resolution.

```python
kb = GlazingKB()                         # construction never imports glazing
candidates = kb.search("give")           # refs prefixed by resource, e.g. "propbank:give.01"
candidates = kb.search("give", types=["verbnet", "wordnet"])
entity = kb.resolve("propbank:give.01")  # bare id defaults to PropBank
edges = kb.neighbors("propbank:give.01", rels=["verbnet_classes"])
```

`resolve` carries the resolved cross-references in the entity's `same_as`, so a
single resolve doubles as a SemLink lookup. `neighbors` folds a sub-one
confidence into the edge relation (for example `verbnet_classes@0.85`). The
`lang` argument is ignored, since glazing's resources are English-only.

glazing requires the `lairs[lexical]` extra (`glazing>=0.2`) at runtime and is
imported lazily inside the connector, never at module import. The first
glazing-backed method call raises `GlazingNotInstalledError` (a subclass of
`ImportError`) when the extra is absent, with a hint to install
`lairs[lexical]` and run `glazing init` to download the FrameNet, PropBank,
VerbNet, and WordNet data. The data download is a glazing step, separate from
installing the package.

## Requirements at a glance

| Connector | Extra | Key / endpoint | Error when absent |
|---|---|---|---|
| `wikidata` | none (default `httpx`), `lairs[wikidata]` optional | no key, public endpoints | `httpx.HTTPStatusError` on failure |
| `reconciliation` | none (`httpx`) | endpoint URL required | `ReconciliationError` when a service is unadvertised |
| `glazing` | `lairs[lexical]` plus `glazing init` data | none | `GlazingNotInstalledError` on first use |

Licence note: the underlying resources carry their own licences (Wikidata under
CC0, and FrameNet, PropBank, VerbNet, and WordNet under their respective terms).
lairs does not relicense them, so consult each source before redistribution.

## See also

- [Codecs](codecs.md) for ingesting the labels you ground.
- [Dataset API](dataset-api.md) for the records a knowledge base enriches.
