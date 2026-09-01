"""The judgment-study surface: a graph of judgment records joined by AT-URI.

A judgment study is an experiment definition (the response scale, the task, and
how items were presented) together with the judgment sets its participants
produced. This surface loads that graph and exposes it the way a judgment study
is actually explored: the participants who judged, the items (the linguistic
stimuli) they judged, the raw judgments as a participant-by-item matrix, and
per-item and per-participant summaries.

The graph is held in a :class:`lairs.store.pool.ModelPool` keyed by AT-URI, so a
judgment's ``item`` objectRef resolves to the expression it names even though the
judged expressions live in a separate account. Loading enumerates the study
authority's experiment definitions and judgment sets, then follows every AT-URI
reference, transitively and across account boundaries, to pull in the judged
expressions.

The record :class:`pub.layers.judgment.ExperimentDef`, :class:`JudgmentSet`, and
:class:`Judgment` models are imported qualified as ``judgment_records.*`` to
avoid clashing with the surface types defined here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

from lairs._aturi import authority_of
from lairs.data._loader import decode_envelope, load_graph
from lairs.data.dataset import Dataset
from lairs.records._generated import expression as expression_records
from lairs.records._generated import judgment as judgment_records
from lairs.store.pool import ModelPool

if TYPE_CHECKING:
    from lairs.atproto.pds import PdsClient
    from lairs.data._loader import PdsSource

__all__ = [
    "ItemDistribution",
    "JudgmentRow",
    "JudgmentStudy",
    "LabelCount",
    "Participant",
    "ParticipantSummary",
    "load_judgment_study",
]

# the collection NSIDs a judgment study is built from.
_EXPERIMENT_DEF_NSID = "pub.layers.judgment.experimentDef"
_JUDGMENT_SET_NSID = "pub.layers.judgment.judgmentSet"
_EXPRESSION_NSID = "pub.layers.expression.expression"

# the study's own records: the experiment definition and the judgment sets. The
# study authority is enumerated for these; refs are not followed per-item, since
# a large study cites tens of thousands of item expressions.
_STUDY_NSID_MODELS: dict[str, type[dx.Model]] = {
    _EXPERIMENT_DEF_NSID: judgment_records.ExperimentDef,
    _JUDGMENT_SET_NSID: judgment_records.JudgmentSet,
}

# the judged items are expressions, loaded in bulk from the stimulus accounts the
# item refs name rather than one getRecord per item.
_EXPRESSION_MODELS: dict[str, type[dx.Model]] = {
    _EXPRESSION_NSID: expression_records.Expression,
}

# the recognised load sources, mirroring load_corpus.
_SOURCE_PDS = "pds"
_SOURCE_APPVIEW = "appview"
_SOURCE_AUTO = "auto"
_VALID_SOURCES = frozenset({_SOURCE_PDS, _SOURCE_APPVIEW, _SOURCE_AUTO})


class LabelCount(dx.Model):
    """One categorical response label and how often it was chosen.

    Attributes
    ----------
    label : str
        The categorical judgment label.
    count : int
        How many judgments carried this label for the item.
    """

    label: str = dx.field(description="the categorical judgment label")
    count: int = dx.field(description="how many judgments carried this label")


class Participant(dx.Model):
    """A participant (agent) who produced a judgment set.

    Attributes
    ----------
    id : str
        The participant's stable identifier: the agent id, or its DID or name
        when no id is set.
    name : str or None
        The participant's display name, when known.
    did : str or None
        The participant's DID, when the agent is identified by one.
    """

    id: str = dx.field(description="the participant's stable identifier")
    name: str | None = dx.field(default=None, description="the participant's name")
    did: str | None = dx.field(default=None, description="the participant's DID")


class JudgmentRow(dx.Model):
    """One judgment: a participant's response to an item, flattened for browse.

    Attributes
    ----------
    participant_id : str
        The judging participant's identifier.
    item_ref : str
        The AT-URI of the judged item (an expression).
    item_text : str or None
        The item's text, when the referenced expression resolved in the pool.
    scalar_value : int or None
        The scalar response, when the task collects a scalar rating.
    categorical_value : str or None
        The categorical label, when the task collects a categorical choice.
    confidence : int or None
        The participant's stated confidence, scaled 0-1000.
    """

    participant_id: str = dx.field(description="the judging participant's id")
    item_ref: str = dx.field(description="AT-URI of the judged item")
    item_text: str | None = dx.field(
        default=None,
        description="the item's text, when the item expression resolved",
    )
    scalar_value: int | None = dx.field(
        default=None,
        description="the scalar response, when the task is scalar",
    )
    categorical_value: str | None = dx.field(
        default=None,
        description="the categorical label, when the task is categorical",
    )
    confidence: int | None = dx.field(
        default=None,
        description="stated confidence, scaled 0-1000",
    )


class ItemDistribution(dx.Model):
    """The distribution of judgments over one item.

    Attributes
    ----------
    item_ref : str
        The AT-URI of the item.
    item_text : str or None
        The item's text, when it resolved.
    count : int
        How many judgments the item received.
    mean : float or None
        The mean scalar response, when the item drew scalar responses.
    minimum : int or None
        The least scalar response, when scalar.
    maximum : int or None
        The greatest scalar response, when scalar.
    label_counts : tuple of LabelCount
        Per-label counts, when the item drew categorical responses.
    """

    item_ref: str = dx.field(description="AT-URI of the item")
    item_text: str | None = dx.field(
        default=None,
        description="the item's text, when resolved",
    )
    count: int = dx.field(description="how many judgments the item received")
    mean: float | None = dx.field(
        default=None,
        description="mean scalar response, when scalar",
    )
    minimum: int | None = dx.field(
        default=None,
        description="least scalar response, when scalar",
    )
    maximum: int | None = dx.field(
        default=None,
        description="greatest scalar response, when scalar",
    )
    label_counts: tuple[dx.Embed[LabelCount], ...] = dx.field(
        default_factory=tuple,
        description="per-label counts, when categorical",
    )


class ParticipantSummary(dx.Model):
    """A participant and how many judgments they contributed.

    Attributes
    ----------
    participant_id : str
        The participant's identifier.
    name : str or None
        The participant's display name, when known.
    judgment_count : int
        How many judgments the participant contributed to the study.
    """

    participant_id: str = dx.field(description="the participant's id")
    name: str | None = dx.field(default=None, description="the participant's name")
    judgment_count: int = dx.field(description="judgments the participant made")


def _participant_id(agent: judgment_records.AgentRef | None) -> str | None:
    """Return a stable identifier for a judgment set's agent, or ``None``."""
    if agent is None:
        return None
    return agent.id or agent.did or agent.name


def _item_ref(judgment: judgment_records.Judgment) -> str | None:
    """Return the AT-URI a judgment's ``item`` objectRef names, if any."""
    return judgment.item.recordRef


class JudgmentStudy:
    """A graph of judgment records joined by AT-URI cross-references.

    Parameters
    ----------
    pool : lairs.store.pool.ModelPool or None, optional
        A pre-populated pool of records keyed by AT-URI. When omitted an empty
        pool is created.
    uri : str or None, optional
        The AT-URI the study was loaded from (an experiment definition or the
        judgment-namespace account).

    Attributes
    ----------
    pool : lairs.store.pool.ModelPool
        The AT-URI-keyed record graph.
    uri : str or None
        The AT-URI the study was loaded from, if any.
    """

    def __init__(
        self,
        pool: ModelPool | None = None,
        *,
        uri: str | None = None,
    ) -> None:
        self.pool = pool if pool is not None else ModelPool()
        self.uri = uri

    @classmethod
    def new(cls, uri: str | None = None) -> JudgmentStudy:
        """Create an empty study surface for authoring.

        Parameters
        ----------
        uri : str or None, optional
            The AT-URI the study is authored under.

        Returns
        -------
        JudgmentStudy
            An empty study surface.
        """
        return cls(uri=uri)

    def add_record(self, uri: str, record: dx.Model) -> None:
        """Add any judgment record to the graph by AT-URI.

        Parameters
        ----------
        uri : str
            The AT-URI of the record.
        record : didactic.api.Model
            The record to add (an experiment def, judgment set, or expression).
        """
        self.pool.add(uri, record)

    @property
    def experiment(self) -> judgment_records.ExperimentDef | None:
        """Return the study's experiment definition, or ``None`` when unloaded."""
        for ref in self.pool.uris():
            model = self.pool.get(ref)
            if isinstance(model, judgment_records.ExperimentDef):
                return model
        return None

    @property
    def scale(self) -> tuple[int | None, int | None]:
        """Return the response scale ``(minimum, maximum)`` from the experiment."""
        experiment = self.experiment
        if experiment is None:
            return (None, None)
        return (experiment.scaleMin, experiment.scaleMax)

    def _judgment_sets(self) -> list[judgment_records.JudgmentSet]:
        """Return the pooled judgment-set records, in pool order."""
        return [
            model
            for ref in self.pool.uris()
            if isinstance(
                (model := self.pool.get(ref)),
                judgment_records.JudgmentSet,
            )
        ]

    def judgment_sets(self) -> Dataset[judgment_records.JudgmentSet]:
        """Return a dataset of the study's judgment sets, one per participant.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of judgment-set models, in pool order.
        """
        return Dataset(self._judgment_sets(), model=judgment_records.JudgmentSet)

    def participants(self) -> Dataset[Participant]:
        """Return the distinct participants who produced the judgment sets.

        A participant is identified by its agent id (falling back to DID or
        name); the first judgment set seen for an id fixes its name and DID.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of participants, in first-seen order.
        """
        seen: dict[str, Participant] = {}
        for judgment_set in self._judgment_sets():
            agent = judgment_set.agent
            participant_id = _participant_id(agent)
            if participant_id is None or participant_id in seen:
                continue
            seen[participant_id] = Participant(
                id=participant_id,
                name=agent.name if agent is not None else None,
                did=agent.did if agent is not None else None,
            )
        return Dataset(list(seen.values()), model=Participant)

    def judgments(self) -> Dataset[JudgmentRow]:
        """Return every judgment flattened to a participant-by-item row.

        Each row carries the judging participant, the judged item's AT-URI and
        (when the expression resolved in the pool) its text, and the response
        (scalar or categorical) plus confidence.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of flattened judgment rows.
        """
        rows: list[JudgmentRow] = []
        for judgment_set in self._judgment_sets():
            participant_id = _participant_id(judgment_set.agent) or ""
            for judgment in judgment_set.judgments:
                item_ref = _item_ref(judgment)
                rows.append(
                    JudgmentRow(
                        participant_id=participant_id,
                        item_ref=item_ref or "",
                        item_text=self._item_text(item_ref),
                        scalar_value=judgment.scalarValue,
                        categorical_value=judgment.categoricalValue,
                        confidence=judgment.confidence,
                    ),
                )
        return Dataset(rows, model=JudgmentRow)

    def _item_text(self, item_ref: str | None) -> str | None:
        """Return the text of the expression an item ref names, if it resolved."""
        if item_ref is None:
            return None
        target = self.pool.resolve(item_ref)
        if isinstance(target, expression_records.Expression):
            return target.text
        return None

    def item_distributions(self) -> Dataset[ItemDistribution]:
        """Return the distribution of judgments over each item.

        Items are grouped by their AT-URI. Scalar responses report ``count``,
        ``mean``, ``minimum``, and ``maximum``; categorical responses report
        per-label counts. An item drawing both kinds reports each over its own
        responses.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of per-item distributions, in first-seen item order.
        """
        scalars: dict[str, list[int]] = {}
        labels: dict[str, dict[str, int]] = {}
        texts: dict[str, str | None] = {}
        order: list[str] = []
        for row in self.judgments():
            item_ref = row.item_ref
            if item_ref not in texts:
                texts[item_ref] = row.item_text
                order.append(item_ref)
            if row.scalar_value is not None:
                scalars.setdefault(item_ref, []).append(row.scalar_value)
            if row.categorical_value is not None:
                bucket = labels.setdefault(item_ref, {})
                bucket[row.categorical_value] = bucket.get(row.categorical_value, 0) + 1
        distributions = [
            _distribution_for(
                item_ref,
                texts[item_ref],
                scalars.get(item_ref, []),
                labels.get(item_ref, {}),
            )
            for item_ref in order
        ]
        return Dataset(distributions, model=ItemDistribution)

    def participant_summaries(self) -> Dataset[ParticipantSummary]:
        """Return each participant with the number of judgments they contributed.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of per-participant summaries, in first-seen order.
        """
        counts: dict[str, int] = {}
        names: dict[str, str | None] = {}
        order: list[str] = []
        for judgment_set in self._judgment_sets():
            agent = judgment_set.agent
            participant_id = _participant_id(agent)
            if participant_id is None:
                continue
            if participant_id not in counts:
                counts[participant_id] = 0
                names[participant_id] = agent.name if agent is not None else None
                order.append(participant_id)
            counts[participant_id] += len(judgment_set.judgments)
        summaries = [
            ParticipantSummary(
                participant_id=participant_id,
                name=names[participant_id],
                judgment_count=counts[participant_id],
            )
            for participant_id in order
        ]
        return Dataset(summaries, model=ParticipantSummary)


def _distribution_for(
    item_ref: str,
    item_text: str | None,
    scalars: list[int],
    labels: dict[str, int],
) -> ItemDistribution:
    """Build an item distribution from its scalar and categorical responses."""
    count = len(scalars) + sum(labels.values())
    mean = sum(scalars) / len(scalars) if scalars else None
    minimum = min(scalars) if scalars else None
    maximum = max(scalars) if scalars else None
    label_counts = tuple(
        LabelCount(label=label, count=labels[label]) for label in sorted(labels)
    )
    return ItemDistribution(
        item_ref=item_ref,
        item_text=item_text,
        count=count,
        mean=mean,
        minimum=minimum,
        maximum=maximum,
        label_counts=label_counts,
    )


def _item_authorities(study: JudgmentStudy) -> set[str]:
    """Return the distinct authorities of the item refs the study's judgments cite."""
    authorities: set[str] = set()
    for judgment_set in study._judgment_sets():  # noqa: SLF001  (same-module helper)
        for judgment in judgment_set.judgments:
            item_ref = _item_ref(judgment)
            if item_ref:
                authorities.add(authority_of(item_ref))
    return authorities


def _load_item_expressions(study: JudgmentStudy, client: PdsSource) -> None:
    """Bulk-load the stimulus expressions the study's judgments reference.

    The judged items are expressions in one or a few stimulus accounts. Rather
    than one ``getRecord`` per item (tens of thousands in a large study), each
    referenced authority's expression collection is read once with
    ``list_records`` and its expressions are added to the pool, so every item
    ref resolves to its text.
    """
    for authority in _item_authorities(study):
        for envelope in client.list_records(authority, _EXPRESSION_NSID):
            decoded = decode_envelope(envelope, _EXPRESSION_MODELS)
            if decoded is not None:
                record_uri, model = decoded
                study.pool.add(record_uri, model)


def _load_from_pds(
    uri: str,
    client: PdsSource,
    *,
    follow_refs: bool = True,
) -> JudgmentStudy:
    """Load a judgment-study graph from a PDS.

    Reads the study authority's experiment definition and judgment sets. When
    ``follow_refs`` is true, the stimulus expressions the judgments reference are
    bulk-loaded from their accounts so item text resolves; when false, only the
    study's own records are read and item text is left unresolved.
    """
    pool = load_graph(uri, _STUDY_NSID_MODELS, client, follow_refs=False)
    study = JudgmentStudy(pool, uri=uri)
    if follow_refs:
        _load_item_expressions(study, client)
    return study


def load_judgment_study(  # noqa: PLR0913  (the loader threads several optional knobs)
    uri: str,
    *,
    source: str = "auto",
    cache_dir: str | None = None,
    revision: str | None = None,
    pds_client: PdsClient | None = None,
    follow_refs: bool = True,
) -> JudgmentStudy:
    """Load a judgment study by AT-URI from a PDS.

    Enumerates the AT-URI's authority for experiment definitions and judgment
    sets, then follows every AT-URI reference across account boundaries,
    transitively, to pull in the judged expressions even when they live in a
    separate account. Pass an experiment-definition AT-URI, or the
    judgment-namespace account's AT-URI, whose authority hosts the judgment
    records. The ``pds`` source reads directly from a PDS; ``auto`` uses the
    injected PDS client. A client may be injected for testing without network
    setup.

    Parameters
    ----------
    uri : str
        The experiment (or judgment-account) AT-URI whose authority is
        enumerated.
    source : str, optional
        The source to load from (``"pds"``, ``"appview"``, or ``"auto"``).
    cache_dir : str or None, optional
        A local cache directory (reserved; not yet used).
    revision : str or None, optional
        A revision to resolve (reserved; not yet used).
    pds_client : lairs.atproto.pds.PdsClient or None, optional
        An injected PDS client, required for the ``pds`` source.
    follow_refs : bool, optional
        Whether to follow AT-URI references across account boundaries. Defaults
        to ``True``.

    Returns
    -------
    JudgmentStudy
        The loaded judgment-study graph.

    Raises
    ------
    ValueError
        When ``source`` is not a recognised source value.
    NotImplementedError
        When the appview source is requested (no appview judgment query yet), or
        the PDS source is requested without an injected client.
    """
    if source not in _VALID_SOURCES:
        valid = sorted(_VALID_SOURCES)
        msg = f"unknown judgment source {source!r}; expected one of {valid}"
        raise ValueError(msg)
    _ = (cache_dir, revision)
    if source in {_SOURCE_PDS, _SOURCE_AUTO} and pds_client is not None:
        return _load_from_pds(uri, pds_client, follow_refs=follow_refs)
    if source == _SOURCE_APPVIEW:
        msg = "appview judgment loading is not available; inject a pds_client"
        raise NotImplementedError(msg)
    msg = "judgment loading needs an injected pds_client until discovery lands"
    raise NotImplementedError(msg)
