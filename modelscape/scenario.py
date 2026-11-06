"""Scenarios: frozen, versioned task spaces that any target can be mapped against."""

from __future__ import annotations

import json
import math
import re
import textwrap
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from modelscape.analysis import BoundaryCriterion, Results
from modelscape.analysis.threshold import Answer
from modelscape.core.coordinates import same_value
from modelscape.core.experiments import Grid, Sweep
from modelscape.core.files import parse_scalar
from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput
from modelscape.core.serialization import AxisValue, canonical_json
from modelscape.core.tasks import Variant
from modelscape.execution import ExecutionConfig, Experiment
from modelscape.measures import CallableDifference, CallableMetric, DifferenceMeasure, Response
from modelscape.report import Provenance, Report
from modelscape.space import Axis, TaskSpace
from modelscape.targets import Target

if TYPE_CHECKING:
    from pandas import DataFrame

CORRECT = "correct"
ANSWERED = "answered"
ANSWER_CHANGE = "answer_change"
ALL = "all"


@dataclass(frozen=True, kw_only=True, eq=False)
class Scenario:
    """A task space with a fixed protocol, so every target is mapped the same way.

    ``answer`` reads the answer from an output, or ``None`` when it cannot; compared with each
    task's ``reference()`` it scores every target. ``groups`` name case subsets with their own
    scorecards. Bump ``version`` whenever results could change.
    """

    name: str
    version: str
    description: str
    task_space: TaskSpace[Any]
    answer: Answer
    repetitions: int = 5
    measures: Sequence[DifferenceMeasure] = ()
    design: Sweep | Grid = field(default_factory=Sweep)
    groups: Mapping[str, Sequence[str]] = field(default_factory=dict[str, Sequence[str]])
    criterion: BoundaryCriterion = field(default_factory=BoundaryCriterion)
    seed: int = 0

    @property
    def identity(self) -> Identity:
        return Identity(name=self.name, version=self.version)

    def describe(self) -> str:
        """The scenario's cases, axes, and variants, checked, and the calls it makes per target."""
        space = self.task_space
        variants = list(self.variants())
        lines = [
            f"{self.name} {self.version}: {self.description}",
            f"  cases     {len(space.cases)}"
            + "".join(f", {name} {len(cases)}" for name, cases in self.groups.items()),
            *(
                f"  axis      {axis.name} ({axis.scale}): {_order(axis)}, baseline {axis.baseline}"
                for axis in space.axes
            ),
            f"  variants  {len(variants)}, all checked",
            f"  calls     {len(variants) * self.repetitions} per target",
        ]
        return "\n".join(lines)

    def example(self) -> str:
        """Every variant of the first case: what it changes, its correct answer, and its prompt."""
        space = self.task_space
        case = next(iter(space.cases))
        variants = [
            space.variant(case, coordinate)
            for coordinate in self.design.coordinates(space.coordinates)
        ]
        lines = [f"case {case}"]
        system = variants[0].prompt.system
        if system:
            lines += ["", "system", textwrap.indent(system, "  ")]
        for variant in variants:
            changed = ", ".join(
                f"{axis}={value}" for axis, value in _changed(variant, space.baseline)
            )
            lines += [
                "",
                f"{changed or 'baseline'}  correct: {variant.reference}",
                textwrap.indent(variant.prompt.last, "  "),
            ]
        return "\n".join(lines)

    def variants(self) -> Iterator[Variant]:
        """Every variant the scenario asks each target, case by case."""
        space = self.task_space
        return space.variants(self.design.coordinates(space.coordinates))

    def prompts(self) -> DataFrame:
        """Every variant as one row: its case, coordinate, changed axes, prompt, and answer.

        Requires the ``pandas`` extra: ``uv add "modelscape[pandas]"``.
        """
        try:
            import pandas
        except ModuleNotFoundError as error:
            raise ModuleNotFoundError(
                'Scenario.prompts requires the pandas extra: uv add "modelscape[pandas]"'
            ) from error
        baseline = self.task_space.baseline
        return pandas.DataFrame(
            [
                {
                    "case": variant.case_id,
                    **variant.coordinate,
                    "changed": ", ".join(axis for axis, _ in _changed(variant, baseline)),
                    "system": variant.prompt.system,
                    "prompt": variant.prompt.last,
                    "reference": variant.reference,
                    "variant": variant.id,
                }
                for variant in self.variants()
            ]
        )

    def experiment(
        self, targets: Sequence[Target], execution: ExecutionConfig | None = None
    ) -> Experiment:
        """The experiment that maps ``targets`` with this scenario."""
        parameters = self.identity.model_dump(mode="json")
        return Experiment(
            task_space=self.task_space,
            targets=targets,
            repetitions=self.repetitions,
            point_metrics=[
                CallableMetric(self._correct, name=CORRECT, parameters=parameters),
                CallableMetric(self._answered, name=ANSWERED, parameters=parameters),
            ],
            difference_measures=[
                CallableDifference(self._change, name=ANSWER_CHANGE, parameters=parameters),
                *self.measures,
            ],
            design=self.design,
            execution=execution or ExecutionConfig(),
            seed=self.seed,
            scenario=self.identity,
        )

    def report(self, results: Results) -> Report:
        """Scorecards, divergences, and provenance of a run of this scenario."""
        targets = [target.name for target in results.experiment.targets]
        groups = {ALL: results.experiment.case_ids, **self.groups}
        return Report(
            scenario=self.identity,
            experiment=results.experiment.id,
            scorecards=tuple(
                results.scorecard(
                    CORRECT,
                    ANSWER_CHANGE,
                    target=target,
                    group=group,
                    answered=ANSWERED,
                    answer=self.answer,
                    cases=cases,
                    criterion=self.criterion,
                )
                for target in targets
                for group, cases in groups.items()
            ),
            divergences=tuple(
                results.divergence(ANSWER_CHANGE, targets[0], other, criterion=self.criterion)
                for other in targets[1:]
            ),
            provenance=Provenance.of(results),
        )

    def _correct(self, variant: Variant, output: TargetOutput) -> float:
        return float(_same(self.answer(output), variant.reference))

    def _answered(self, variant: Variant, output: TargetOutput) -> float:
        return float(self.answer(output) is not None)

    def _change(self, start: Response, end: Response) -> float:
        return float(not _same(self.answer(start.output), self.answer(end.output)))


def json_reply(output: TargetOutput) -> dict[str, object]:
    """The JSON object in an output, read from its first ``{`` to its last ``}``.

    Empty when the output holds no JSON object.
    """
    text = output.as_text()
    try:
        parsed: object = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], parsed) if isinstance(parsed, dict) else {}


def json_field(name: str, choices: Iterable[AxisValue] | None = None) -> Answer:
    """An ``answer`` that reads field ``name`` of a JSON reply, such as ``{"verdict": "close"}``.

    With ``choices``, any other value counts as no answer.
    """
    allowed = None if choices is None else tuple(choices)

    def read(output: TargetOutput) -> AxisValue | None:
        value = json_reply(output).get(name)
        if not isinstance(value, bool | int | float | str):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value if allowed is None or any(_same(value, item) for item in allowed) else None

    return read


def text_match(pattern: str, choices: Iterable[AxisValue]) -> Answer:
    """An ``answer`` that reads the first match of ``pattern``, or of its first group.

    A match that spells a number or a boolean becomes one; any value not in ``choices`` counts
    as no answer.
    """
    expression = re.compile(pattern)
    allowed = tuple(choices)

    def read(output: TargetOutput) -> AxisValue | None:
        found = expression.search(output.as_text())
        if found is None:
            return None
        value = parse_scalar(found.group(1) if expression.groups else found.group(0))
        return value if any(_same(value, choice) for choice in allowed) else None

    return read


def _same(first: object, second: object) -> bool:
    return canonical_json(first) == canonical_json(second)


def _changed(variant: Variant, baseline: Mapping[str, AxisValue]) -> list[tuple[str, AxisValue]]:
    return [
        (axis, value)
        for axis, value in variant.coordinate.items()
        if not same_value(value, baseline[axis])
    ]


def _order(axis: Axis[Any, Any]) -> str:
    separator = ", " if axis.scale == "nominal" else " < "
    return separator.join(map(str, axis.values))
