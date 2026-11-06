from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeAlias

from modelscape.analysis.index import ResultIndex
from modelscape.analysis.profiles import BoundaryCandidate, BoundaryCriterion, build_profile
from modelscape.analysis.statistics import Estimate, Inference
from modelscape.analysis.threshold import Answer, Threshold, measure_threshold
from modelscape.analysis.transitions import (
    MetricPoint,
    Transition,
    measure_metric,
    measure_transition,
)
from modelscape.core.coordinates import Coordinate, Scale
from modelscape.core.experiments import ExperimentRecord
from modelscape.core.serialization import FrozenModel, canonical_json
from modelscape.core.tasks import Variant

Role: TypeAlias = Literal["invariant", "causal"]


class AxisScore(FrozenModel):
    """One axis of a scorecard.

    ``scale`` decides which steps are tested. ``role`` is ``causal`` when changing this axis
    alone, between any two evaluated coordinates, changes the correct answer of some case, and
    ``invariant`` otherwise. ``accuracy`` follows the axis with every other axis at its
    baseline. ``shifts`` are the steps where answers changed beyond run-to-run variation:
    adjacent steps on an ordinal or numeric axis, comparisons with the baseline on a nominal
    one. ``threshold`` compares where the answer flips with where it should, on a causal
    numeric axis when the answers could be read.
    """

    axis: str
    scale: Scale
    role: Role
    accuracy: tuple[MetricPoint, ...]
    shifts: tuple[BoundaryCandidate, ...]
    threshold: Threshold | None = None


class Scorecard(FrozenModel):
    """Headline numbers for one target on one case group.

    ``answered`` is the share of outputs, over every coordinate, from which an answer could be
    read. ``spurious_change`` is answer change beyond noise where the correct answer stays the
    same; ``missed_change`` is the share of answers that stay the same where it moves. Both are
    ideally zero, and ``None`` when nothing could be measured.
    """

    target: str
    group: str
    cases: tuple[str, ...]
    accuracy: Estimate
    answered: float | None
    spurious_change: float | None
    missed_change: float | None
    axes: tuple[AxisScore, ...]

    @property
    def invariant_shifts(self) -> int:
        """The number of shifts on invariant axes, where answers should not change."""
        return sum(len(axis.shifts) for axis in self.axes if axis.role == "invariant")


class Divergence(FrozenModel):
    """Where two targets answer differently beyond the run-to-run variation of each.

    ``contrasts`` holds one comparison per evaluated coordinate; ``candidates`` are the ones
    ``criterion`` selects.
    """

    first: str
    second: str
    measure: str
    contrasts: tuple[Transition, ...]
    candidates: tuple[BoundaryCandidate, ...]


def build_scorecard(
    index: ResultIndex,
    experiment: ExperimentRecord,
    variants: Sequence[Variant],
    *,
    target: str,
    group: str,
    metric: str,
    measure: str,
    answered: str | None,
    answer: Answer | None,
    cases: Sequence[str],
    criterion: BoundaryCriterion,
    inference: Inference,
) -> Scorecard:
    space = experiment.space
    baseline = space.baseline
    answers = {
        (variant.case_id, variant.coordinate): canonical_json(variant.reference)
        for variant in variants
    }

    def changes(case: str, coordinate: Coordinate) -> bool:
        return answers[(case, coordinate)] != answers[(case, baseline)]

    axes: list[AxisScore] = []
    for name in space.axis_names:
        profile = build_profile(
            index,
            experiment,
            target=target,
            axis=name,
            measure=measure,
            fixed=None,
            cases=cases,
            inference=inference,
            criterion=criterion,
        )
        role = axis_role(name, experiment.coordinates, cases, answers)
        scale = space.axis(name).scale
        axes.append(
            AxisScore(
                axis=name,
                scale=scale,
                role=role,
                accuracy=tuple(point for point in profile.metrics if point.metric == metric),
                shifts=profile.candidate_boundaries,
                threshold=measure_threshold(
                    index,
                    experiment,
                    answers,
                    target=target,
                    axis=name,
                    metric=metric,
                    answer=answer,
                    cases=cases,
                    inference=inference,
                )
                if answer is not None and role == "causal" and scale == "numeric"
                else None,
            )
        )
    spurious: list[float] = []
    missed: list[float] = []
    for coordinate in experiment.coordinates:
        if coordinate == baseline:
            continue
        transition = measure_transition(
            index,
            target=target,
            measure=measure,
            view="baseline",
            axis=None,
            start=baseline,
            end=coordinate,
            cases=cases,
            inference=inference,
        )
        for item in transition.per_case:
            if not changes(item.case, coordinate) and item.excess is not None:
                spurious.append(item.excess)
            if changes(item.case, coordinate) and item.between is not None:
                missed.append(1.0 - item.between)
    accuracy = measure_metric(
        index, target=target, metric=metric, coordinate=baseline, cases=cases, inference=inference
    )
    return Scorecard(
        target=target,
        group=group,
        cases=tuple(cases),
        accuracy=accuracy.estimate,
        answered=None
        if answered is None
        else _answered(index, experiment, target, answered, cases),
        spurious_change=_mean(spurious),
        missed_change=_mean(missed),
        axes=tuple(axes),
    )


def build_divergence(
    index: ResultIndex,
    experiment: ExperimentRecord,
    *,
    first: str,
    second: str,
    measure: str,
    cases: Sequence[str],
    criterion: BoundaryCriterion,
    inference: Inference,
) -> Divergence:
    contrasts = tuple(
        measure_transition(
            index,
            target=first,
            versus=second,
            measure=measure,
            view="contrast",
            axis=None,
            start=coordinate,
            end=coordinate,
            cases=cases,
            inference=inference,
        )
        for coordinate in experiment.coordinates
    )
    return Divergence(
        first=first,
        second=second,
        measure=measure,
        contrasts=contrasts,
        candidates=criterion.select(contrasts),
    )


def axis_role(
    axis: str,
    coordinates: Sequence[Coordinate],
    cases: Sequence[str],
    answers: dict[tuple[str, Coordinate], str],
) -> Role:
    """``causal`` when changing ``axis`` alone changes the correct answer of some case."""
    seen: dict[tuple[str, str], set[str]] = {}
    for case in cases:
        for coordinate in coordinates:
            rest = Coordinate({name: value for name, value in coordinate.items() if name != axis})
            seen.setdefault((case, rest.key), set()).add(answers[(case, coordinate)])
    return "causal" if any(len(found) > 1 for found in seen.values()) else "invariant"


def _answered(
    index: ResultIndex,
    experiment: ExperimentRecord,
    target: str,
    metric: str,
    cases: Sequence[str],
) -> float | None:
    return _mean(
        [
            float(value)
            for case in cases
            for coordinate in experiment.coordinates
            for value in index.metric_values(metric, index.cell(target, case, coordinate))[0]
        ]
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
