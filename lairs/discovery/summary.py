"""Corpus-to-summary mapping and dataset filtering.

Projects a generated ``Corpus`` record (or a record envelope carrying one) into
the flat ``DatasetSummary`` discovery shape, evaluates a ``DatasetFilter`` over a
summary, and extracts the server-side facets ``listCorpora`` supports.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs._aturi import authority_of, nsid_of
from lairs.discovery.models import DatasetSummary
from lairs.records._generated import corpus as corpus_records

if TYPE_CHECKING:
    from lairs._types import JsonValue
    from lairs.atproto.pds import QueryParams, RecordEnvelope
    from lairs.discovery.models import DatasetFilter

__all__ = [
    "corpus_from_value",
    "listcorpora_params",
    "matches",
    "summary_from_corpus",
    "summary_from_envelope",
]

_CORPUS_NSID = "pub.layers.corpus.corpus"
"""The collection NSID of a corpus record."""

_DATASET_LIKE_NSIDS = frozenset(
    {
        "pub.layers.corpus.corpus",
        "pub.layers.corpus.membership",
        "pub.layers.expression.expression",
        "pub.layers.annotation.annotationLayer",
        "pub.layers.segmentation.segmentation",
        "pub.layers.media.media",
        "pub.layers.eprint.eprint",
        "pub.layers.eprint.dataLink",
        "pub.layers.ontology.ontology",
    },
)
"""Collection NSIDs that hold dataset-shaped records, for TOC highlighting."""


def _has_adjudication(corpus: corpus_records.Corpus) -> bool:
    """Return whether a corpus declares an adjudication step.

    Parameters
    ----------
    corpus : lairs.records._generated.corpus.Corpus
        The corpus record.

    Returns
    -------
    bool
        ``True`` when the corpus's annotation design carries an adjudication spec.
    """
    design = corpus.annotationDesign
    return design is not None and design.adjudication is not None


def summary_from_corpus(
    corpus: corpus_records.Corpus,
    *,
    uri: str,
    did: str,
    handle: str | None = None,
    source_endpoint: str | None = None,
) -> DatasetSummary:
    """Project a corpus record into a ``DatasetSummary``.

    Parameters
    ----------
    corpus : lairs.records._generated.corpus.Corpus
        The corpus record to project.
    uri : str
        The corpus AT-URI.
    did : str
        The owning repository DID.
    handle : str or None, optional
        The owning handle, when known.
    source_endpoint : str or None, optional
        The PDS or appview the corpus was read from.

    Returns
    -------
    DatasetSummary
        The flat discovery summary.
    """
    return DatasetSummary(
        uri=uri,
        did=did,
        handle=handle,
        name=corpus.name,
        description=corpus.description,
        domain=corpus.domain,
        domain_uri=corpus.domainUri,
        language=corpus.language,
        languages=corpus.languages or (),
        license=corpus.license,
        version=corpus.version,
        expression_count=corpus.expressionCount,
        created_at=corpus.createdAt.isoformat(),
        ontology_refs=corpus.ontologyRefs or (),
        eprint_refs=corpus.eprintRefs or (),
        has_adjudication=_has_adjudication(corpus),
        source_endpoint=source_endpoint,
    )


def corpus_from_value(value: JsonValue) -> corpus_records.Corpus | None:
    """Decode a record value into a ``Corpus``, or ``None`` on failure.

    The wire-only ``$type`` discriminator is dropped before validation, since
    the generated models do not declare it.

    Parameters
    ----------
    value : JsonValue
        The record value to decode.

    Returns
    -------
    lairs.records._generated.corpus.Corpus or None
        The decoded corpus, or ``None`` when the value is not a decodable corpus.
    """
    if not isinstance(value, dict):
        return None
    payload = {key: item for key, item in value.items() if key != "$type"}
    try:
        return corpus_records.Corpus.model_validate_json(json.dumps(payload))
    except dx.ValidationError:
        return None


def summary_from_envelope(
    envelope: RecordEnvelope,
    *,
    did: str | None = None,
    handle: str | None = None,
    source_endpoint: str | None = None,
) -> DatasetSummary | None:
    """Decode a corpus envelope into a ``DatasetSummary``.

    Returns ``None`` when the envelope is not a corpus record or its value does
    not validate, so a single bad record does not abort a listing.

    Parameters
    ----------
    envelope : lairs.atproto.pds.RecordEnvelope
        The record envelope to decode.
    did : str or None, optional
        The owning DID; derived from the envelope URI when omitted.
    handle : str or None, optional
        The owning handle, when known.
    source_endpoint : str or None, optional
        The PDS or appview the envelope was read from.

    Returns
    -------
    DatasetSummary or None
        The summary, or ``None`` when the record is not a decodable corpus.
    """
    if nsid_of(envelope.uri) != _CORPUS_NSID:
        return None
    corpus = corpus_from_value(envelope.value)
    if corpus is None:
        return None
    resolved_did = did if did is not None else authority_of(envelope.uri)
    return summary_from_corpus(
        corpus,
        uri=envelope.uri,
        did=resolved_did,
        handle=handle,
        source_endpoint=source_endpoint,
    )


def matches(summary: DatasetSummary, flt: DatasetFilter | None) -> bool:
    """Return whether a summary satisfies a filter.

    Parameters
    ----------
    summary : DatasetSummary
        The summary to test.
    flt : DatasetFilter or None
        The filter; ``None`` matches everything.

    Returns
    -------
    bool
        ``True`` when the summary passes every set facet.
    """
    if flt is None:
        return True
    count = summary.expression_count
    language_ok = (
        flt.language is None
        or flt.language == summary.language
        or flt.language in summary.languages
    )
    min_ok = flt.min_expression_count is None or (
        count is not None and count >= flt.min_expression_count
    )
    max_ok = flt.max_expression_count is None or (
        count is not None and count <= flt.max_expression_count
    )
    haystack = f"{summary.name} {summary.description or ''}".lower()
    text_ok = flt.text is None or flt.text.lower() in haystack
    adjudication_ok = (
        flt.has_adjudication is None or flt.has_adjudication == summary.has_adjudication
    )
    return all(
        (
            language_ok,
            flt.domain is None or flt.domain == summary.domain,
            flt.license is None or flt.license == summary.license,
            min_ok,
            max_ok,
            text_ok,
            adjudication_ok,
        ),
    )


def listcorpora_params(repo: str, flt: DatasetFilter | None) -> QueryParams:
    """Build ``listCorpora`` query parameters, pushing the server-side facets.

    Only ``language`` and ``domain`` are server-side facets on ``listCorpora``;
    every other facet is applied client-side over the mapped summaries.

    Parameters
    ----------
    repo : str
        The repository DID or handle to list.
    flt : DatasetFilter or None
        The filter whose server-side facets to push.

    Returns
    -------
    QueryParams
        The query parameters for ``corpus.listCorpora``.
    """
    params: QueryParams = {"repo": repo}
    if flt is not None:
        if flt.language is not None:
            params["language"] = flt.language
        if flt.domain is not None:
            params["domain"] = flt.domain
    return params
