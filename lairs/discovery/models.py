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
        The number of records in the collection, when counted.
    is_dataset_like : bool
        Whether the collection holds dataset-shaped records.
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
