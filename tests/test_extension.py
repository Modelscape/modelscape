from __future__ import annotations

import asyncio
import json
from typing import cast

import pytest
from pydantic import model_validator

from modelscape import (
    Axis,
    CallableDifference,
    CallableMetric,
    CallableTarget,
    Experiment,
    MeasureValue,
    Response,
    Runner,
    TargetOutput,
    TargetRequest,
    Task,
    TaskSpace,
    Variant,
    attribute,
    perturbation,
    realizer,
)
from modelscape.core import SchemaError
from modelscape.measures.callables import MetricFunction


class Contract(Task):
    owner: str
    clauses: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _at_most_three_clauses(self) -> Contract:
        if len(self.clauses) > 3:
            raise ValueError(f"{len(self.clauses)} clauses exceed the limit")
        return self

    @attribute
    def clause_count(self) -> int:
        return len(self.clauses)

    def reference(self) -> str:
        return "approve"


@perturbation
def set_clauses(task: Contract, count: int) -> Contract:
    return task.replace(clauses=tuple(f"clause {index}" for index in range(count)))


@realizer(system="Decide.")
def render(task: Contract) -> str:
    return json.dumps({"options": ["approve", "reject"], "clauses": list(task.clauses)})


CASES = {f"case-{index}": Contract(owner=f"team-{index}") for index in range(3)}


def decide(request: TargetRequest) -> TargetOutput:
    count = len(json.loads(request.prompt.last)["clauses"])
    action = "approve" if count < 2 else "reject"
    return TargetOutput(structured={"action": action, "confidence": 0.9 - 0.1 * count})


def action(output: TargetOutput) -> object:
    return output.structured["action"] if isinstance(output.structured, dict) else None


def correct(variant: Variant, output: TargetOutput) -> float:
    return float(action(output) == variant.reference)


async def judged_correct(variant: Variant, output: TargetOutput) -> MeasureValue:
    await asyncio.sleep(0)
    return MeasureValue(value=correct(variant, output), details={"judge": "async"})


def decision_change(start: Response, end: Response) -> MeasureValue:
    changed = action(start.output) != action(end.output)
    return MeasureValue(
        value=float(changed),
        details={
            "owner": end.variant.task["owner"],
            "reference": end.variant.reference,
            "clauses": [
                start.variant.attributes["clause_count"],
                end.variant.attributes["clause_count"],
            ],
        },
    )


async def confidence_shift(start: Response, end: Response) -> float:
    await asyncio.sleep(0)
    first, second = start.output.structured, end.output.structured
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    return abs(float(str(first["confidence"])) - float(str(second["confidence"])))


def space(limit: int = 3) -> TaskSpace[Contract]:
    return TaskSpace(
        cases=CASES,
        axes=[Axis(Contract.clause_count, range(limit + 1), via=set_clauses, scale="numeric")],
        realizer=render,
    )


async def test_a_complete_custom_test_runs_from_plain_python() -> None:
    experiment = Experiment(
        task_space=space(),
        targets=[CallableTarget(decide, name="decider")],
        repetitions=3,
        point_metrics=[
            CallableMetric(correct, name="accuracy"),
            CallableMetric(judged_correct, name="judged_accuracy"),
        ],
        difference_measures=[
            CallableDifference(decision_change, name="decision_change"),
            CallableDifference(confidence_shift, name="confidence_shift"),
        ],
    )
    results = await Runner().run(experiment)
    profile = results.profile("clause_count", "decision_change")
    assert [t.excess.value for t in profile.local if t.excess] == [0.0, 1.0, 0.0]
    assert [
        (c.transition.start_value, c.transition.end_value) for c in profile.candidate_boundaries
    ] == [(1, 2)]
    assert [point.estimate.value for point in profile.metrics if point.metric == "accuracy"] == [
        1.0,
        1.0,
        0.0,
        0.0,
    ]
    shift = results.profile("clause_count", "confidence_shift").baseline[3]
    assert shift.between is not None
    assert shift.between.value == pytest.approx(0.3)
    detail = next(
        m.details
        for m in results.difference_measurements
        if m.measure.name == "decision_change" and m.value == 1.0
    )
    assert detail["reference"] == "approve"
    assert str(detail["owner"]).startswith("team-")
    judged = [m for m in results.point_measurements if m.measure.name == "judged_accuracy"]
    assert all(m.details == {"judge": "async"} for m in judged)
    assert results.experiment.realizer == render.identity
    assert results.experiment.task_schema == Contract.describe()


def test_grammar_constraints_reject_variants() -> None:
    with pytest.raises(SchemaError, match="4 clauses exceed the limit"):
        space(limit=4).variant("case-0", {"clause_count": 4})


def test_adapters_share_one_identity_shape() -> None:
    adapters = [
        perturbation(name="p", version="2", parameters={"k": 1})(set_clauses.function),
        realizer(name="r", version="2", parameters={"k": 1})(render.function),
        CallableMetric(correct, name="m", version="2", parameters={"k": 1}),
        CallableDifference(decision_change, name="d", version="2", parameters={"k": 1}),
        CallableTarget(decide, name="t", version="2", parameters={"k": 1}),
    ]
    assert [(a.identity.version, a.identity.parameters["k"]) for a in adapters] == [("2", 1)] * 5
    assert (
        CallableMetric(correct, name="m").identity
        != CallableMetric(correct, name="m", version="2").identity
    )


def says_yes(variant: Variant, output: TargetOutput) -> object:
    return "yes"


async def test_measures_reject_non_numeric_results() -> None:
    metric = CallableMetric(cast(MetricFunction, says_yes), name="bad")
    with pytest.raises(TypeError, match="number or MeasureValue"):
        await metric.score([Response(space().variant("case-0"), TargetOutput(text="x"))])
