"""Cross-repo, ref-anchored link queries.

These queries are anchored on a content reference (a corpus, an eprint) rather
than a repository, so an appview that indexes the network answers them across
every repo: who, anywhere, asserts membership in this corpus, or links this
eprint to data. They require an appview endpoint or client, since a PDS can only
answer for its own repository.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.atproto.appview import AppviewClient
from lairs.records._generated.corpus import Membership
from lairs.records._generated.eprint import DataLink

if TYPE_CHECKING:
    from lairs.atproto.pds import QueryParams, RecordEnvelope

__all__ = ["datasets_for_eprint", "members_of_corpus"]


def _appview_for(
    appview: str | None,
    client: AppviewClient | None,
) -> tuple[AppviewClient, bool]:
    """Return an appview client and whether the caller owns (must close) it.

    Parameters
    ----------
    appview : str or None
        An appview base URL.
    client : AppviewClient or None
        An injected appview client.

    Returns
    -------
    tuple
        The client and a flag that is ``True`` when the caller created it.

    Raises
    ------
    ValueError
        If neither an endpoint nor a client is provided.
    """
    if client is not None:
        return client, False
    if appview is None:
        msg = "an appview endpoint or client is required for cross-repo link queries"
        raise ValueError(msg)
    return AppviewClient(appview), True


def _decode_record[T: dx.Model](
    envelope: RecordEnvelope,
    model_cls: type[T],
) -> T | None:
    """Decode an envelope value into a model, or ``None`` on failure.

    Parameters
    ----------
    envelope : lairs.atproto.pds.RecordEnvelope
        The record envelope to decode.
    model_cls : type
        The target model class.

    Returns
    -------
    T or None
        The decoded model, or ``None`` when the value is not a decodable object.
    """
    value = envelope.value
    if not isinstance(value, dict):
        return None
    payload = {key: item for key, item in value.items() if key != "$type"}
    try:
        return model_cls.model_validate_json(json.dumps(payload))
    except dx.ValidationError:
        return None


def members_of_corpus(
    corpus_uri: str,
    *,
    appview: str | None = None,
    appview_client: AppviewClient | None = None,
    split: str | None = None,
) -> tuple[Membership, ...]:
    """List membership records that point at a corpus, across all repos.

    Parameters
    ----------
    corpus_uri : str
        The corpus AT-URI to find members of.
    appview : str or None, optional
        An appview base URL.
    appview_client : AppviewClient or None, optional
        An injected appview client.
    split : str or None, optional
        Restrict to a dataset split (for example ``"train"``).

    Returns
    -------
    tuple of lairs.records._generated.corpus.Membership
        The membership records asserted for the corpus.

    Raises
    ------
    ValueError
        If no appview endpoint or client is available.
    """
    client, owns = _appview_for(appview, appview_client)
    params: QueryParams = {"corpusRef": corpus_uri}
    if split is not None:
        params["split"] = split
    try:
        envelopes = list(client.list("corpus.listMemberships", params))
    finally:
        if owns:
            client.close()
    decoded = [_decode_record(envelope, Membership) for envelope in envelopes]
    return tuple(member for member in decoded if member is not None)


def datasets_for_eprint(
    eprint_uri: str,
    *,
    appview: str | None = None,
    appview_client: AppviewClient | None = None,
    data_kind: str | None = None,
) -> tuple[DataLink, ...]:
    """List data links that point at an eprint, across all repos.

    Parameters
    ----------
    eprint_uri : str
        The eprint AT-URI to find data links for.
    appview : str or None, optional
        An appview base URL.
    appview_client : AppviewClient or None, optional
        An injected appview client.
    data_kind : str or None, optional
        Restrict to a data-kind slug.

    Returns
    -------
    tuple of lairs.records._generated.eprint.DataLink
        The data-link records that reference the eprint.

    Raises
    ------
    ValueError
        If no appview endpoint or client is available.
    """
    client, owns = _appview_for(appview, appview_client)
    params: QueryParams = {"eprintUri": eprint_uri}
    if data_kind is not None:
        params["dataKind"] = data_kind
    try:
        envelopes = list(client.list("eprint.listDataLinks", params))
    finally:
        if owns:
            client.close()
    decoded = [_decode_record(envelope, DataLink) for envelope in envelopes]
    return tuple(link for link in decoded if link is not None)
