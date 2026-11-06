from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence

from pydantic import Field, JsonValue

from modelscape.analysis.index import ResultIndex
from modelscape.analysis.statistics import Inference, holm
from modelscape.analysis.transitions import (
    MetricPoint,
    Transition,
    measure_metric,
    measure_transition,
)
from modelscape.core.coordinates import AxisValue, Coordinate, Scale
from modelscape.core.errors import AnalysisError
from modelscape.core.experiments import ExperimentRecord
from modelscape.core.serialization import FrozenModel


class BoundaryCriterion(FrozenModel):
    """The rule that decides which transitions are candidate boundaries.

    A transition qualifies when its permutation p-value, corrected with Holm's method for the
    number of transitions tested together, is at most ``alpha``, and its estimated excess
    change is larger than ``min_excess``.
    """

    alpha: float = Field(default=0.05, gt=0, lt=1)
    min_excess: float = Field(default=0.0, ge=0)

    def select(self, transitions: Sequence[Transition]) -> tuple[BoundaryCandidate, ...]:
        adjusted = holm([transition.p_value for transition in transitions])
        return tuple(
            BoundaryCandidate(
                transition=transition,
                adjusted_p_value=p_value,
                criterion=self,
                rationale=self._rationale(transition.excess.value, p_value),
            )
            for transition, p_value in zip(transitions, adjusted, strict=True)
            if p_value is not None
            and p_value <= self.alpha
            and transition.excess is not None
            and transition.excess.value > self.min_excess
        )

    def _rationale(self, excess: float, p_value: float) -> str:
        return (
            f"Excess change {excess:.3f} is above {self.min_excess:.3f}, and the "
            f"Holm-corrected permutation p-value {p_value:.3f} is at most {self.alpha:.3f}."
        )


class BoundaryCandidate(FrozenModel):
    """A transition where behavior changed more than run-to-run variation explains.

    It shows where to look. It does not prove a capability threshold, a failure point, or a
    mechanism.
    """

    transition: Transition
    adjusted_p_value: float
    criterion: BoundaryCriterion
    rationale: str


class BehaviorProfile(FrozenModel):
    """How one target's behavior changes along one axis under one difference measure.

    ``baseline`` compares every axis value with the experiment's baseline; at the baseline
    itself this is the run-to-run variation. ``local`` compares each pair of adjacent axis
    values. Other axes stay at ``fixed``. Point metrics at the same coordinates are in
    ``metrics``. ``candidate_boundaries`` are selected from ``steps``.
    """

    target: str
    axis: str
    measure: str
    values: tuple[AxisValue, ...]
    baseline_value: AxisValue
    scale: Scale
    fixed: Coordinate
    cases: tuple[str, ...]
    local: tuple[Transition, ...]
    baseline: tuple[Transition, ...]
    metrics: tuple[MetricPoint, ...]
    candidate_boundaries: tuple[BoundaryCandidate, ...]
    criterion: BoundaryCriterion
    inference: Inference

    @property
    def steps(self) -> tuple[Transition, ...]:
        """The transitions tested for boundaries: neighbors, or the baseline if nominal."""
        return steps(self.scale, self.local, self.baseline)

    def table(self) -> list[dict[str, JsonValue]]:
        return [transition.row() for transition in (*self.local, *self.baseline)]

    def metric_table(self) -> list[dict[str, JsonValue]]:
        return [point.row() for point in self.metrics]


def build_profile(
    index: ResultIndex,
    experiment: ExperimentRecord,
    *,
    target: str,
    axis: str,
    measure: str,
    fixed: Mapping[str, AxisValue] | None,
    cases: Sequence[str],
    inference: Inference,
    criterion: BoundaryCriterion,
) -> BehaviorProfile:
    space = experiment.space
    spec = space.axis(axis)
    line = space.line(axis, fixed)
    require_evaluated(experiment, line)
    local = tuple(
        measure_transition(
            index,
            target=target,
            measure=measure,
            view="local",
            axis=axis,
            start=start,
            end=end,
            cases=cases,
            inference=inference,
        )
        for start, end in (itertools.pairwise(line) if spec.ordered else ())
    )
    baseline = tuple(
        measure_transition(
            index,
            target=target,
            measure=measure,
            view="baseline",
            axis=axis,
            start=space.baseline,
            end=coordinate,
            cases=cases,
            inference=inference,
        )
        for coordinate in line
    )
    metrics = tuple(
        measure_metric(
            index,
            target=target,
            metric=metric.name,
            coordinate=coordinate,
            cases=cases,
            inference=inference,
        )
        for metric in experiment.point_metrics
        for coordinate in line
    )
    return BehaviorProfile(
        target=target,
        axis=axis,
        measure=measure,
        values=spec.values,
        baseline_value=spec.baseline,
        scale=spec.scale,
        fixed=Coordinate({name: value for name, value in line[0].items() if name != axis}),
        cases=tuple(cases),
        local=local,
        baseline=baseline,
        metrics=metrics,
        candidate_boundaries=criterion.select(steps(spec.scale, local, baseline)),
        criterion=criterion,
        inference=inference,
    )


def steps(
    scale: Scale, local: tuple[Transition, ...], baseline: tuple[Transition, ...]
) -> tuple[Transition, ...]:
    if scale == "nominal":
        return tuple(item for item in baseline if item.start != item.end)
    return local


def require_evaluated(experiment: ExperimentRecord, coordinates: Sequence[Coordinate]) -> None:
    evaluated = set(experiment.coordinates)
    missing = [coordinate for coordinate in coordinates if coordinate not in evaluated]
    if missing:
        raise AnalysisError(
            f"Coordinate {missing[0]} was not evaluated by this experiment's "
            f"{experiment.design.kind} design. Use a Grid design over the axes you want "
            "to analyze away from the baseline."
        )
