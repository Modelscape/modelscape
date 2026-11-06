from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal, TypeAlias

import numpy as np
from pydantic import JsonValue

from modelscape.analysis.index import ResultIndex
from modelscape.analysis.statistics import (
    CaseSample,
    ComparisonSample,
    Estimate,
    FloatArray,
    Inference,
    permutation_p_value,
    sample_repeated,
    sample_transition,
    sample_values,
    summarize,
)
from modelscape.core.coordinates import AxisValue, Coordinate
from modelscape.core.errors import AnalysisError
from modelscape.core.serialization import FrozenModel

View: TypeAlias = Literal["local", "baseline", "contrast"]
SamplingUnit: TypeAlias = Literal["case", "repetition"]


class CaseTransition(FrozenModel):
    """One task case's share of a transition, before averaging over cases."""

    case: str
    between: float | None
    within: float | None
    excess: float | None
    observations: int


class CaseMetric(FrozenModel):
    """One task case's average point metric at a coordinate, before averaging over cases."""

    case: str
    value: float
    observations: int


class Transition(FrozenModel):
    """A step between two coordinates, measured within each case and averaged over cases.

    ``between`` is the change across the step, ``within`` the run-to-run variation at both ends,
    ``excess`` their difference, and ``p_value`` a permutation test of the step. A ``contrast``
    compares ``target`` with ``versus`` at one coordinate.
    """

    target: str
    versus: str | None = None
    measure: str
    view: View
    axis: str | None
    start: Coordinate
    end: Coordinate
    between: Estimate | None
    within: Estimate | None
    excess: Estimate | None
    p_value: float | None
    cases: int
    observations: int
    sampling_unit: SamplingUnit
    per_case: tuple[CaseTransition, ...]
    measurement_ids: tuple[str, ...]

    @property
    def ratio(self) -> float | None:
        """Change between divided by variation within, defined when within is positive."""
        if self.between is None or self.within is None or self.within.value <= 0:
            return None
        return self.between.value / self.within.value

    @property
    def start_value(self) -> AxisValue | None:
        return None if self.axis is None else self.start[self.axis]

    @property
    def end_value(self) -> AxisValue | None:
        return None if self.axis is None else self.end[self.axis]

    def row(self) -> dict[str, JsonValue]:
        return {
            "target": self.target,
            "versus": self.versus,
            "measure": self.measure,
            "view": self.view,
            "axis": self.axis,
            "start_value": self.start_value,
            "end_value": self.end_value,
            "start": dict(self.start),
            "end": dict(self.end),
            **_estimate_columns("between", self.between),
            **_estimate_columns("within", self.within),
            **_estimate_columns("excess", self.excess),
            "p_value": self.p_value,
            "ratio": self.ratio,
            "cases": self.cases,
            "observations": self.observations,
            "sampling_unit": self.sampling_unit,
        }


class MetricPoint(FrozenModel):
    """A point metric at one coordinate, averaged over repetitions and then over cases."""

    target: str
    metric: str
    coordinate: Coordinate
    estimate: Estimate
    cases: int
    observations: int
    sampling_unit: SamplingUnit
    per_case: tuple[CaseMetric, ...]
    measurement_ids: tuple[str, ...]

    def row(self) -> dict[str, JsonValue]:
        return {
            "target": self.target,
            "metric": self.metric,
            "coordinate": dict(self.coordinate),
            **_estimate_columns("value", self.estimate),
            "cases": self.cases,
            "observations": self.observations,
            "sampling_unit": self.sampling_unit,
        }


class VariantVariability(FrozenModel):
    """Run-to-run variation of one variant: how much its repeated outputs differ."""

    target: str
    measure: str
    case_id: str
    variant_id: str
    coordinate: Coordinate
    within: Estimate | None
    repetitions: int
    measurement_ids: tuple[str, ...]

    def row(self) -> dict[str, JsonValue]:
        return {
            "target": self.target,
            "measure": self.measure,
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            "coordinate": dict(self.coordinate),
            **_estimate_columns("within", self.within),
            "repetitions": self.repetitions,
        }


def measure_transition(
    index: ResultIndex,
    *,
    target: str,
    measure: str,
    view: View,
    axis: str | None,
    start: Coordinate,
    end: Coordinate,
    cases: Sequence[str],
    inference: Inference,
    versus: str | None = None,
) -> Transition:
    other = versus or target
    rng = inference.generator("transition", target, other, measure, start.key, end.key, *cases)
    samples: list[ComparisonSample] = []
    pooled: list[FloatArray] = []
    splits: list[int] = []
    per_case: list[CaseTransition] = []
    identifiers: list[str] = []
    for case in cases:
        first = index.cell(target, case, start)
        second = index.cell(other, case, end)
        if not first or not second:
            continue
        if start == end and versus is None:
            matrix, used = index.within_matrix(measure, first)
            sample = sample_repeated(matrix, inference, rng)
            identifiers.extend(used)
            observed = len(first)
        else:
            start_matrix, start_ids = index.within_matrix(measure, first)
            end_matrix, end_ids = index.within_matrix(measure, second)
            cross, cross_ids = index.cross_matrix(measure, first, second)
            sample = sample_transition(start_matrix, end_matrix, cross, inference, rng)
            pooled.append(np.block([[start_matrix, cross], [cross.T, end_matrix]]))
            splits.append(len(first))
            identifiers.extend([*cross_ids, *start_ids, *end_ids])
            observed = len(first) + len(second)
        samples.append(sample)
        per_case.append(
            CaseTransition(
                case=case,
                between=_defined(sample.between.value),
                within=_defined(sample.within.value),
                excess=_defined(sample.excess.value),
                observations=observed,
            )
        )
    if not samples:
        raise AnalysisError(
            f"Target '{target}' has no successful observations at both {start} and {end}."
        )
    within = summarize([sample.within for sample in samples], inference, rng)
    between = (
        within
        if start == end and versus is None
        else summarize([sample.between for sample in samples], inference, rng)
    )
    return Transition(
        target=target,
        versus=versus,
        measure=measure,
        view=view,
        axis=axis,
        start=start,
        end=end,
        between=between,
        within=within,
        excess=summarize([sample.excess for sample in samples], inference, rng),
        p_value=permutation_p_value(pooled, splits, inference, rng) if pooled else None,
        cases=len(samples),
        observations=sum(item.observations for item in per_case),
        sampling_unit=_unit(len(samples)),
        per_case=tuple(per_case),
        measurement_ids=tuple(dict.fromkeys(identifiers)),
    )


def measure_metric(
    index: ResultIndex,
    *,
    target: str,
    metric: str,
    coordinate: Coordinate,
    cases: Sequence[str],
    inference: Inference,
) -> MetricPoint:
    rng = inference.generator("metric", target, metric, coordinate.key, *cases)
    samples: list[CaseSample] = []
    per_case: list[CaseMetric] = []
    identifiers: list[str] = []
    for case in cases:
        observations = index.cell(target, case, coordinate)
        if observations:
            values, used = index.metric_values(metric, observations)
            sample = sample_values(values, inference, rng)
            samples.append(sample)
            per_case.append(CaseMetric(case=case, value=sample.value, observations=len(used)))
            identifiers.extend(used)
    estimate = summarize(samples, inference, rng)
    if estimate is None:
        raise AnalysisError(f"Target '{target}' has no successful observations at {coordinate}.")
    return MetricPoint(
        target=target,
        metric=metric,
        coordinate=coordinate,
        estimate=estimate,
        cases=len(samples),
        observations=len(identifiers),
        sampling_unit=_unit(len(samples)),
        per_case=tuple(per_case),
        measurement_ids=tuple(identifiers),
    )


def measure_variability(
    index: ResultIndex,
    *,
    target: str,
    measure: str,
    case_id: str,
    variant_id: str,
    coordinate: Coordinate,
    inference: Inference,
) -> VariantVariability:
    rng = inference.generator("variability", target, measure, variant_id)
    observations = index.cell(target, case_id, coordinate)
    matrix, identifiers = index.within_matrix(measure, observations)
    within = (
        summarize([sample_repeated(matrix, inference, rng).within], inference, rng)
        if observations
        else None
    )
    return VariantVariability(
        target=target,
        measure=measure,
        case_id=case_id,
        variant_id=variant_id,
        coordinate=coordinate,
        within=within,
        repetitions=len(observations),
        measurement_ids=tuple(identifiers),
    )


def _unit(cases: int) -> SamplingUnit:
    return "case" if cases > 1 else "repetition"


def _defined(value: float) -> float | None:
    return None if math.isnan(value) else value


def _estimate_columns(prefix: str, estimate: Estimate | None) -> dict[str, JsonValue]:
    return {
        prefix: None if estimate is None else estimate.value,
        f"{prefix}_lower": None if estimate is None else estimate.lower,
        f"{prefix}_upper": None if estimate is None else estimate.upper,
    }
