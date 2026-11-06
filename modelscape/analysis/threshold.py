from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence

import numpy as np

from modelscape.analysis.index import ResultIndex
from modelscape.analysis.statistics import Estimate, FloatArray, Inference, interval
from modelscape.core.coordinates import AxisValue, Coordinate
from modelscape.core.experiments import ExperimentRecord
from modelscape.core.observations import TargetOutput
from modelscape.core.serialization import FrozenModel, canonical_json

Answer = Callable[[TargetOutput], AxisValue | None]

QUARTILES = 2 * math.log(3)
PENALTY = np.diag([1e-6, 0.01])
ITERATIONS = 50


class Threshold(FrozenModel):
    """Where a target's answer flips along a numeric axis, and where the correct answer does.

    Each read answer counts as 1 when it is the case's correct answer at the top of the axis.
    The correct answer flips midway between the last value where it differs and the first
    where it holds; ``reference`` is that point averaged over the cases where it flips once.
    A logistic curve is fitted to the answers against the axis value measured from each case's
    own flip. ``offset`` is where the curve crosses one half, in axis units: positive when the
    target flips later than it should. ``width`` is how far the axis moves between a quarter
    and three quarters, and cannot be resolved below the spacing of the axis values. Both are
    ``None`` when the curve does not cross one half within the axis. Intervals resample cases,
    then repetitions.
    """

    reference: float
    offset: Estimate | None
    width: Estimate | None
    cases: int
    observations: int
    measurement_ids: tuple[str, ...]

    @property
    def flip(self) -> Estimate | None:
        """Where the target's answer flips, in axis values."""
        if self.offset is None:
            return None
        return Estimate(
            value=self.reference + self.offset.value,
            lower=None if self.offset.lower is None else self.reference + self.offset.lower,
            upper=None if self.offset.upper is None else self.reference + self.offset.upper,
        )


def measure_threshold(
    index: ResultIndex,
    experiment: ExperimentRecord,
    references: Mapping[tuple[str, Coordinate], str],
    *,
    target: str,
    axis: str,
    metric: str,
    answer: Answer,
    cases: Sequence[str],
    inference: Inference,
) -> Threshold | None:
    line = experiment.space.line(axis)
    values = [float(coordinate[axis]) for coordinate in line]
    span = values[-1] - values[0]
    flips: list[float] = []
    rows: list[tuple[int, float, int, int]] = []
    identifiers: list[str] = []
    for case in cases:
        top = references[(case, line[-1])]
        flip = _flip(values, [references[(case, coordinate)] == top for coordinate in line])
        if flip is None:
            continue
        for value, coordinate in zip(values, line, strict=True):
            observations = index.cell(target, case, coordinate)
            read = [
                canonical_json(item) for o in observations if (item := answer(o.output)) is not None
            ]
            if read:
                rows.append((len(flips), (value - flip) / span, read.count(top), len(read)))
                identifiers.extend(index.metric_values(metric, observations)[1])
        flips.append(flip)
    if not rows:
        return None
    owner = np.array([row[0] for row in rows])
    position = np.array([row[1] for row in rows])
    hits = np.array([row[2] for row in rows], dtype=np.float64)
    totals = np.array([row[3] for row in rows], dtype=np.float64)
    rng = inference.generator("threshold", target, axis, *cases)
    picks = rng.integers(0, len(flips), size=(inference.resamples, len(flips)))
    drawn = np.zeros((inference.resamples, len(flips)))
    np.add.at(drawn, (np.arange(inference.resamples)[:, np.newaxis], picks), 1.0)
    weights = drawn[:, owner]
    redrawn = rng.binomial(totals.astype(np.int64), hits / totals, size=weights.shape)
    intercept, slope = _fit(
        position, np.vstack([hits, weights * redrawn]), np.vstack([totals, weights * totals])
    ).T
    crossing = -intercept / slope
    defined = (slope > 0) & (crossing >= position.min()) & (crossing <= position.max())
    offset = np.where(defined, crossing * span, np.nan)
    width = np.where(defined, QUARTILES / slope * span, np.nan)
    return Threshold(
        reference=float(np.mean(flips)),
        offset=_estimate(offset, inference),
        width=_estimate(width, inference),
        cases=len(flips),
        observations=int(totals.sum()),
        measurement_ids=tuple(identifiers),
    )


def _flip(values: Sequence[float], top: Sequence[bool]) -> float | None:
    first = top.index(True)
    if first == 0 or not all(top[first:]):
        return None
    return (values[first - 1] + values[first]) / 2


def _fit(position: FloatArray, hits: FloatArray, totals: FloatArray) -> FloatArray:
    design = np.column_stack([np.ones_like(position), position])
    coefficients: FloatArray = np.zeros((hits.shape[0], 2))
    for _ in range(ITERATIONS):
        chance = 1 / (1 + np.exp(-np.clip(coefficients @ design.T, -30, 30)))
        gradient = (hits - totals * chance) @ design - coefficients @ PENALTY
        curvature: FloatArray = np.einsum(
            "rm,mi,mj->rij", totals * chance * (1 - chance), design, design
        )
        solved = np.linalg.solve(curvature + PENALTY, gradient[..., np.newaxis])
        step: FloatArray = solved[..., 0].astype(np.float64, copy=False)
        coefficients += step
        if np.abs(step).max() < 1e-9:
            break
    return coefficients


def _estimate(values: FloatArray, inference: Inference) -> Estimate | None:
    return None if math.isnan(values[0]) else interval(float(values[0]), values[1:], inference)
