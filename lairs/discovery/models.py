"""Discovery result models.

dx.Model value types for dataset discovery: a denormalized corpus summary, a
repository table of contents, and a facet filter. These are the shapes the
discovery API returns and the CLI renders. ``DatasetSummary`` is also reused as
the corpus-derived core of the Tier 3 index card.
"""

from __future__ import annotations

import didactic.api as dx

__all__ = [
    "CollectionCount",
    "CollectionFilter",
    "CollectionSummary",
    "DatasetFilter",
    "DatasetSummary",
    "RepoTableOfContents",
]


class DatasetSummary(dx.Model):
    """A denormalized corpus card for discovery listings.

    A flat, readable projection of a ``pub.layers.corpus.corpus`` record plus the
    actor and source it was found through, so a listing renders one row per
    dataset without dumping records.

    Attributes
    ----------
    uri : str
        The corpus AT-URI.
    did : str
        The owning repository DID.
    name : str
        The corpus name.
    handle : str or None
        The owning handle, when it was resolved.
    description : str or None
        The corpus description.
    domain : str or None
        The corpus domain slug.
    domain_uri : str or None
        The AT-URI of the corpus domain definition node.
    language : str or None
        The primary BCP-47 language tag.
    languages : tuple of str
        All languages represented in the corpus.
    license : str or None
        The license identifier.
    version : str or None
        The corpus version label.
    expression_count : int or None
        The number of expressions in the corpus.
    created_at : str or None
        The ISO 8601 creation timestamp.
    ontology_refs : tuple of str
        The ontology AT-URIs the corpus uses.
    eprint_refs : tuple of str
        The eprint AT-URIs the corpus links.
    has_adjudication : bool
        Whether the corpus declares an adjudication step.
    source_endpoint : str or None
        The PDS or appview the summary was read from.
    """

    uri: str = dx.field(description="corpus AT-URI")
    did: str = dx.field(description="owning repository DID")
    name: str = dx.field(description="corpus name")
    handle: str | None = dx.field(
        default=None,
        description="owning handle, when it was resolved",
    )
    description: str | None = dx.field(default=None, description="corpus description")
    domain: str | None = dx.field(default=None, description="corpus domain slug")
    domain_uri: str | None = dx.field(
        default=None,
        description="AT-URI of the corpus domain definition node",
    )
    language: str | None = dx.field(
        default=None,
        description="primary BCP-47 language tag",
    )
    languages: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="all languages represented in the corpus",
    )
    license: str | None = dx.field(default=None, description="license identifier")
    version: str | None = dx.field(default=None, description="corpus version label")
    expression_count: int | None = dx.field(
        default=None,
        description="number of expressions in the corpus",
    )
    created_at: str | None = dx.field(
        default=None,
        description="ISO 8601 creation timestamp",
    )
    ontology_refs: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="ontology AT-URIs the corpus uses",
    )
    eprint_refs: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="eprint AT-URIs the corpus links",
    )
    has_adjudication: bool = dx.field(
        default=False,
        description="whether the corpus declares an adjudication step",
    )
    source_endpoint: str | None = dx.field(
        default=None,
        description="PDS or appview the summary was read from",
    )


class CollectionCount(dx.Model):
    """A repository collection NSID with an optional record count.

    Attributes
    ----------
    nsid : str
        The collection NSID.
    count : int or None
        The number of records in the collection, when counted. When the count
        was capped, this is the cap and ``capped`` is ``True``.
    is_dataset_like : bool
        Whether the collection holds dataset-shaped records.
    capped : bool
        Whether the count reached a requested cap and stopped early, so the
        collection holds at least ``count`` records rather than exactly that
        many.
    """

    nsid: str = dx.field(description="collection NSID")
    count: int | None = dx.field(
        default=None,
        description="number of records in the collection, when counted",
    )
    is_dataset_like: bool = dx.field(
        default=False,
        description="whether the collection holds dataset-shaped records",
    )
    capped: bool = dx.field(
        default=False,
        description="whether the count stopped early at a requested cap",
    )


class RepoTableOfContents(dx.Model):
    """An actor's repository inventory: identity plus per-collection counts.

    Attributes
    ----------
    did : str
        The repository DID.
    handle : str or None
        The repository handle, when known.
    pds_endpoint : str or None
        The PDS endpoint the inventory was read from.
    collections : tuple of CollectionCount
        The collections present in the repository.
    dataset_collections : tuple of str
        The dataset-like collection NSIDs, highlighted for convenience.
    """

    did: str = dx.field(description="repository DID")
    handle: str | None = dx.field(
        default=None,
        description="repository handle, when known",
    )
    pds_endpoint: str | None = dx.field(
        default=None,
        description="PDS endpoint the inventory was read from",
    )
    collections: tuple[dx.Embed[CollectionCount], ...] = dx.field(
        default_factory=tuple,
        description="collections present in the repository",
    )
    dataset_collections: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="dataset-like collection NSIDs, highlighted",
    )


class DatasetFilter(dx.Model):
    """A facet and text filter over dataset summaries.

    Server-side facets (``language``, ``domain``) are pushed into ``listCorpora``
    parameters on the appview path; the rest are applied client-side over the
    mapped summaries.

    Attributes
    ----------
    language : str or None
        Keep corpora whose primary or listed languages include this tag.
    domain : str or None
        Keep corpora with this domain slug.
    license : str or None
        Keep corpora with this license identifier.
    min_expression_count : int or None
        Keep corpora with at least this many expressions.
    max_expression_count : int or None
        Keep corpora with at most this many expressions.
    text : str or None
        Keep corpora whose name or description contains this substring.
    has_adjudication : bool or None
        Keep corpora that do (or do not) declare an adjudication step.
    """

    language: str | None = dx.field(default=None, description="language tag to match")
    domain: str | None = dx.field(default=None, description="domain slug to match")
    license: str | None = dx.field(
        default=None,
        description="license identifier to match",
    )
    min_expression_count: int | None = dx.field(
        default=None,
        description="minimum expression count",
    )
    max_expression_count: int | None = dx.field(
        default=None,
        description="maximum expression count",
    )
    text: str | None = dx.field(
        default=None,
        description="case-insensitive substring over name and description",
    )
    has_adjudication: bool | None = dx.field(
        default=None,
        description="require corpora to declare (or not) an adjudication step",
    )


class CollectionSummary(dx.Model):
    """A denormalized catalogue-collection card for discovery listings.

    A flat, readable projection of a ``pub.layers.catalog.collection`` record
    plus the actor and source it was found through, so a browse listing renders
    one row per collection without paging its produces. The collection is the
    citable, browsable artifact for a dataset as a whole; ``kind`` carries
    container-ness (``project``, ``language-group`` habitually contain other
    collections) so a listing distinguishes a project node from a treebank leaf.

    Attributes
    ----------
    uri : str
        The collection AT-URI.
    did : str
        The owning repository DID.
    name : str
        The collection name.
    kind : str
        The collection kind slug (``treebank``, ``project``, ``lexicon``, ...).
    handle : str or None
        The owning handle, when it was resolved.
    description : str or None
        The collection description.
    kind_uri : str or None
        The AT-URI of the collection-kind definition node.
    languages : tuple of str
        Canonical BCP-47 language tags the collection covers.
    license : str or None
        The license facet (SPDX slug or expression).
    access : str or None
        The access-condition slug (``open``, ``registration-required``, ...).
    stability : str or None
        The lifecycle-state slug (``active``, ``deprecated``, ...).
    depth : int or None
        The number of ``parentRef`` hops from the containment root.
    parent_ref : str or None
        The AT-URI of the containing collection, when nested.
    root_ref : str or None
        The AT-URI of the containment root, denormalized for subtree queries.
    citable : bool
        Whether the collection declares itself the level to cite (its
        ``citation.creditPolicy`` is ``cite-self`` or ``cite-both``).
    member_count : int or None
        The number of nested-collection (``member``) edges, when counted.
    produce_count : int or None
        The number of produce edges, when counted.
    version : str or None
        The collection version or release designation.
    modalities : tuple of str
        The distinct modality slugs across the collection's content buckets.
    annotation_subkinds : tuple of str
        The distinct annotation-subkind slugs across the content buckets.
    source_methods : tuple of str
        The distinct production-method slugs across the content buckets.
    created_at : str or None
        The ISO 8601 creation timestamp.
    eprint_refs : tuple of str
        The eprint AT-URIs the collection links.
    source_endpoint : str or None
        The PDS or appview the summary was read from.
    """

    uri: str = dx.field(description="collection AT-URI")
    did: str = dx.field(description="owning repository DID")
    name: str = dx.field(description="collection name")
    kind: str = dx.field(description="collection kind slug")
    handle: str | None = dx.field(
        default=None,
        description="owning handle, when it was resolved",
    )
    description: str | None = dx.field(
        default=None,
        description="collection description",
    )
    kind_uri: str | None = dx.field(
        default=None,
        description="AT-URI of the collection-kind definition node",
    )
    languages: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="canonical BCP-47 language tags the collection covers",
    )
    license: str | None = dx.field(default=None, description="license facet")
    access: str | None = dx.field(
        default=None,
        description="access-condition slug",
    )
    stability: str | None = dx.field(
        default=None,
        description="lifecycle-state slug",
    )
    depth: int | None = dx.field(
        default=None,
        description="number of parentRef hops from the containment root",
    )
    parent_ref: str | None = dx.field(
        default=None,
        description="AT-URI of the containing collection, when nested",
    )
    root_ref: str | None = dx.field(
        default=None,
        description="AT-URI of the containment root",
    )
    citable: bool = dx.field(
        default=False,
        description="whether the collection declares itself the level to cite",
    )
    member_count: int | None = dx.field(
        default=None,
        description="number of nested-collection edges, when counted",
    )
    produce_count: int | None = dx.field(
        default=None,
        description="number of produce edges, when counted",
    )
    version: str | None = dx.field(
        default=None,
        description="collection version or release designation",
    )
    modalities: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="distinct modality slugs across the content buckets",
    )
    annotation_subkinds: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="distinct annotation-subkind slugs across the content buckets",
    )
    source_methods: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="distinct production-method slugs across the content buckets",
    )
    created_at: str | None = dx.field(
        default=None,
        description="ISO 8601 creation timestamp",
    )
    eprint_refs: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="eprint AT-URIs the collection links",
    )
    source_endpoint: str | None = dx.field(
        default=None,
        description="PDS or appview the summary was read from",
    )


class CollectionFilter(dx.Model):
    """A facet and text filter over collection summaries.

    Carries the server-side facets of ``catalog.listCollections``. The scalar
    facets (``parent_ref``, ``root_ref``, ``depth``, ``citable_only``, ``text``,
    ``sort``) are pushed into the query parameters on the appview path; the array
    facets are applied client-side over the mapped summaries, mirroring how
    ``DatasetFilter`` splits ``listCorpora``.

    Attributes
    ----------
    kind : tuple of str
        Keep collections whose kind slug is any of these.
    kind_uri : tuple of str
        Keep collections whose kind-definition-node URI is any of these.
    parent_ref : str or None
        Keep only the direct children of this collection.
    root_ref : str or None
        Keep the whole containment subtree rooted here.
    depth : int or None
        Keep collections at exactly this depth from their root.
    citable_only : bool
        Keep only collections that declare themselves citable.
    languages : tuple of str
        Keep collections covering any of these canonical BCP-47 tags.
    modality : tuple of str
        Keep collections whose contents declare any of these modality slugs.
    annotation_subkind : tuple of str
        Keep collections whose contents declare any of these subkind slugs.
    source_method : tuple of str
        Keep collections whose contents declare any of these method slugs.
    spdx : tuple of str
        Keep collections whose license facet is any of these SPDX identifiers.
    access : tuple of str
        Keep collections whose access-condition slug is any of these.
    stability : tuple of str
        Keep collections whose lifecycle-state slug is any of these.
    text : str or None
        Keep collections whose name or description contains this substring.
    sort : str or None
        Result ordering (``relevance``, ``name``, ``created``, ``released``,
        ``size``); pushed server-side and otherwise advisory.
    """

    kind: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="collection-kind slugs to match",
    )
    kind_uri: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="collection-kind definition-node URIs to match",
    )
    parent_ref: str | None = dx.field(
        default=None,
        description="keep only direct children of this collection",
    )
    root_ref: str | None = dx.field(
        default=None,
        description="keep the whole subtree rooted at this collection",
    )
    depth: int | None = dx.field(
        default=None,
        description="keep collections at exactly this depth from their root",
    )
    citable_only: bool = dx.field(
        default=False,
        description="keep only collections that declare themselves citable",
    )
    languages: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="canonical BCP-47 tags to match",
    )
    modality: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="modality slugs over contents to match",
    )
    annotation_subkind: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="annotation-subkind slugs over contents to match",
    )
    source_method: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="production-method slugs over contents to match",
    )
    spdx: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="SPDX license identifiers to match",
    )
    access: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="access-condition slugs to match",
    )
    stability: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="lifecycle-state slugs to match",
    )
    text: str | None = dx.field(
        default=None,
        description="case-insensitive substring over name and description",
    )
    sort: str | None = dx.field(
        default=None,
        description="result ordering pushed server-side",
    )
