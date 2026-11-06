from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, model_validator

from modelscape import (
    Axis,
    CallableDifference,
    Grid,
    Node,
    Response,
    Scenario,
    Task,
    TaskSpace,
    attribute,
    json_field,
    json_reply,
    perturbation,
    realizer,
)
from modelscape.measures import TokenJaccardDistance

Reliability = Literal["low", "medium", "high"]
WEIGHT: dict[str, int] = {"low": 1, "medium": 2, "high": 3}


class Hypothesis(Node):
    key: str
    statement: str


class Report(Node):
    id: str
    claim: str
    source: str
    reliability: Reliability
    supports: str


class Incident(Task):
    question: str
    hypotheses: tuple[Hypothesis, ...]
    leading: str
    reports: tuple[Report, ...]

    @model_validator(mode="after")
    def _well_formed(self) -> Incident:
        keys = {hypothesis.key for hypothesis in self.hypotheses}
        if self.leading not in keys or not {report.supports for report in self.reports} <= keys:
            raise ValueError("Every hypothesis referred to must be declared.")
        if len({report.id for report in self.reports}) != len(self.reports):
            raise ValueError("Report ids must be unique.")
        return self

    @attribute
    def corroboration(self) -> int:
        return sum(not self.rival(report) for report in self.reports)

    @attribute
    def conflict(self) -> int:
        return sum(self.rival(report) for report in self.reports)

    @attribute
    def conflict_reliability(self) -> str:
        rivals = [report.reliability for report in self.reports if self.rival(report)]
        return max(rivals, key=WEIGHT.__getitem__, default="none")

    @attribute
    def length(self) -> int:
        return len(self.reports)

    def reference(self) -> str:
        support = {key.key: 0 for key in self.hypotheses}
        for report in self.reports:
            support[report.supports] += WEIGHT[report.reliability]
        return max(support, key=lambda key: (support[key], key == self.leading))

    def rival(self, report: Report) -> bool:
        return report.supports != self.leading


class Rival(Node):
    claim: str
    source: str


class Dossier(Node):
    task: Incident
    rivals: tuple[Rival, ...]


DOSSIERS = TypeAdapter(dict[str, Dossier]).validate_json(
    Path(__file__).with_name("incidents.json").read_text(encoding="utf-8")
)


def dossier_of(task: Incident) -> Dossier:
    return next(item for item in DOSSIERS.values() if item.task.question == task.question)


@perturbation(free=["length"])
def set_corroboration(task: Incident, count: int) -> Incident:
    seed = dossier_of(task).task
    support = [item for item in seed.reports if not seed.rival(item)][:count]
    return task.replace(reports=(*support, *(item for item in task.reports if task.rival(item))))


@perturbation(free=["length"])
def set_conflict(task: Incident, count: int) -> Incident:
    first = next(item for item in task.reports if task.rival(item))
    extra = [
        first.model_copy(update={"id": f"R{index}", "claim": rival.claim, "source": rival.source})
        for index, rival in enumerate(dossier_of(task).rivals, start=1)
    ]
    support = [item for item in task.reports if not task.rival(item)]
    return task.replace(reports=(*support, *[first, *extra][:count]))


@perturbation
def set_conflict_reliability(task: Incident, level: str) -> Incident:
    return task.replace(
        reports=tuple(
            item.model_copy(update={"reliability": level}) if task.rival(item) else item
            for item in task.reports
        )
    )


@realizer(
    system=(
        "You are an analyst. Weigh each report by its source reliability. Reply with only a "
        'JSON object: {"summary": at most four sentences, "assessment": the key of the most '
        'likely hypothesis, "confidence": a number from 0 to 1}.'
    )
)
def brief(task: Incident) -> str:
    hypotheses = "\n".join(f"{item.key}: {item.statement}" for item in task.hypotheses)
    reports = "\n".join(
        f"[{item.id}] ({item.source}, {item.reliability} reliability) {item.claim}"
        for item in task.reports
    )
    return f"Question: {task.question}\n\nHypotheses:\n{hypotheses}\n\nReports:\n{reports}"


assessment = json_field("assessment", ("H1", "H2", "H3"))


def confidence_shift(start: Response, end: Response) -> float:
    values = [json_reply(response.output).get("confidence") for response in (start, end)]
    first, second = (float(value) if isinstance(value, int | float) else 0.0 for value in values)
    return abs(first - second)


SCENARIO = Scenario(
    name="evidence",
    version="2",
    description="Assessing competing hypotheses as rival evidence grows in amount and reliability.",
    task_space=TaskSpace(
        cases={name: dossier.task for name, dossier in DOSSIERS.items()},
        axes=[
            Axis(
                Incident.corroboration,
                (1, 2, 3, 4),
                via=set_corroboration,
                scale="numeric",
                baseline=4,
            ),
            Axis(Incident.conflict, (1, 2, 3), via=set_conflict, scale="numeric"),
            Axis(
                Incident.conflict_reliability,
                ("low", "medium", "high"),
                via=set_conflict_reliability,
                scale="ordinal",
            ),
        ],
        realizer=brief,
    ),
    answer=assessment,
    measures=[
        CallableDifference(confidence_shift, name="confidence_shift"),
        TokenJaccardDistance(),
    ],
    design=Grid(),
    repetitions=3,
)
