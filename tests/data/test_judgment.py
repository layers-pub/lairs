"""Unit tests for lairs.data.judgment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lairs.atproto.pds import RecordEnvelope
from lairs.data import judgment as judgment_mod
from lairs.data.judgment import JudgmentStudy, load_judgment_study
from lairs.records._generated.defs import AgentRef, ObjectRef
from lairs.records._generated.expression import Expression
from lairs.records._generated.judgment import ExperimentDef, Judgment, JudgmentSet

if TYPE_CHECKING:
    from collections.abc import Iterator

    import didactic.api as dx

_NOW = datetime(2026, 1, 1, tzinfo=UTC)

_STUDY = "did:plc:study"
_ITEMS = "did:plc:items"
_EXPERIMENT = f"at://{_STUDY}/pub.layers.judgment.experimentDef/x"
_SET_A = f"at://{_STUDY}/pub.layers.judgment.judgmentSet/a"
_SET_B = f"at://{_STUDY}/pub.layers.judgment.judgmentSet/b"
_ITEM_1 = f"at://{_ITEMS}/pub.layers.expression.expression/i1"
_ITEM_2 = f"at://{_ITEMS}/pub.layers.expression.expression/i2"

_EXPERIMENT_DEF_NSID = "pub.layers.judgment.experimentDef"
_JUDGMENT_SET_NSID = "pub.layers.judgment.judgmentSet"
_EXPRESSION_NSID = "pub.layers.expression.expression"


def _experiment() -> ExperimentDef:
    return ExperimentDef(
        name="Demo", taskType="ordinal-scale", scaleMin=1, scaleMax=7, createdAt=_NOW
    )


def _item(ref: str, value: int) -> Judgment:
    return Judgment(item=ObjectRef(recordRef=ref), scalarValue=value)


def _set_a() -> JudgmentSet:
    return JudgmentSet(
        agent=AgentRef(id="mturk/1", name="Worker 1"),
        judgments=(_item(_ITEM_1, 6), _item(_ITEM_2, 2)),
        experimentRef=_EXPERIMENT,
        createdAt=_NOW,
    )


def _set_b() -> JudgmentSet:
    return JudgmentSet(
        agent=AgentRef(id="mturk/2", name="Worker 2"),
        judgments=(_item(_ITEM_1, 7), _item(_ITEM_2, 3)),
        experimentRef=_EXPERIMENT,
        createdAt=_NOW,
    )


def _expression(text: str) -> Expression:
    return Expression(id=text, kind="sentence", createdAt=_NOW, text=text)


def _envelope(uri: str, model: dx.Model) -> RecordEnvelope:
    value = json.loads(model.model_dump_json())
    value["$type"] = uri.split("/")[-2]
    return RecordEnvelope(uri=uri, cid="cid", value=value)


class _FakePds:
    """A fake PDS returning canned envelopes by collection."""

    def __init__(self, by_collection: dict[str, list[RecordEnvelope]]) -> None:
        self._by = by_collection

    def list_records(
        self,
        repo: str,
        collection: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Iterator[RecordEnvelope]:
        _ = (repo, limit, cursor)
        yield from self._by.get(collection, [])


def _study_fake() -> _FakePds:
    return _FakePds(
        {
            _EXPERIMENT_DEF_NSID: [_envelope(_EXPERIMENT, _experiment())],
            _JUDGMENT_SET_NSID: [
                _envelope(_SET_A, _set_a()),
                _envelope(_SET_B, _set_b()),
            ],
            _EXPRESSION_NSID: [
                _envelope(_ITEM_1, _expression("The cat sat.")),
                _envelope(_ITEM_2, _expression("Sat cat the on mat.")),
            ],
        },
    )


def test_load_judgment_study_surfaces_scale_participants_and_items() -> None:
    fake = _study_fake()
    study = load_judgment_study(_EXPERIMENT, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    assert study.scale == (1, 7)
    assert study.experiment is not None
    assert study.experiment.name == "Demo"
    assert [p.id for p in study.participants()] == ["mturk/1", "mturk/2"]
    summaries = {
        s.participant_id: s.judgment_count for s in study.participant_summaries()
    }
    assert summaries == {"mturk/1": 2, "mturk/2": 2}
    assert len(list(study.judgments())) == 4


def test_load_judgment_study_resolves_item_text_and_distributions() -> None:
    fake = _study_fake()
    study = load_judgment_study(_EXPERIMENT, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    by_text = {d.item_text: d for d in study.item_distributions()}
    assert set(by_text) == {"The cat sat.", "Sat cat the on mat."}
    first = by_text["The cat sat."]
    assert first.count == 2
    assert first.mean == pytest.approx(6.5)
    assert (first.minimum, first.maximum) == (6, 7)


def test_load_judgment_study_no_follow_refs_leaves_item_text_unresolved() -> None:
    fake = _study_fake()
    study = load_judgment_study(
        _EXPERIMENT,
        source="pds",
        pds_client=fake,  # ty: ignore[invalid-argument-type]
        follow_refs=False,
    )
    texts = {d.item_text for d in study.item_distributions()}
    assert texts == {None}
    # the raw judgments and distributions are still complete, keyed by ref.
    assert {d.item_ref for d in study.item_distributions()} == {_ITEM_1, _ITEM_2}


def test_categorical_distribution_reports_label_counts() -> None:
    study = JudgmentStudy.new()
    study.add_record(_EXPERIMENT, _experiment())
    judgments = (
        Judgment(item=ObjectRef(recordRef=_ITEM_1), categoricalValue="yes"),
        Judgment(item=ObjectRef(recordRef=_ITEM_1), categoricalValue="no"),
        Judgment(item=ObjectRef(recordRef=_ITEM_1), categoricalValue="yes"),
    )
    study.add_record(
        _SET_A,
        JudgmentSet(
            agent=AgentRef(id="mturk/1"),
            judgments=judgments,
            experimentRef=_EXPERIMENT,
            createdAt=_NOW,
        ),
    )
    distribution = next(iter(study.item_distributions()))
    assert distribution.count == 3
    assert distribution.mean is None
    assert {lc.label: lc.count for lc in distribution.label_counts} == {
        "yes": 2,
        "no": 1,
    }


def test_load_judgment_study_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown judgment source"):
        load_judgment_study(_EXPERIMENT, source="bogus")


def test_load_judgment_study_appview_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="appview"):
        load_judgment_study(_EXPERIMENT, source="appview")


def test_load_judgment_study_without_client_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="pds_client"):
        load_judgment_study(_EXPERIMENT, source="auto")


def test_exports() -> None:
    assert set(judgment_mod.__all__) == {
        "ItemDistribution",
        "JudgmentRow",
        "JudgmentStudy",
        "LabelCount",
        "Participant",
        "ParticipantSummary",
        "load_judgment_study",
    }
