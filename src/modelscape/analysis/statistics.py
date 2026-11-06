"""Statistics over repeated runs: bootstrap intervals and permutation tests.

Each task case is one independent unit. Every quantity is first computed within a case, from
that case's own repeated outputs, and then averaged over cases. Intervals come from a
two-level bootstrap: draw cases with replacement, then draw each drawn case's outputs with
replacement, and recompute. Pairs of outputs are never treated as independent samples, so
adding repetitions cannot inflate the number of independent cases. With a single case, only
repetitions are resampled. A run is never compared with itself.

Excess change is the average difference between two conditions minus the average difference
within each condition. The permutation test shuffles outputs between the two conditions
within each case and asks how often a shuffled split shows at least as much excess change as
the real one. A small p-value means the controlled change moved behavior beyond ordinary
run-to-run variation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from pydantic import Field

from modelscape.core.serialization import FrozenModel, content_hash

TOLERANCE = 1e-12

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


class Inference(FrozenModel):
    """Settings for bootstrap intervals and permutation tests.

    The same settings always give the same results. Set ``permutations`` to zero to skip the
    permutation tests.
    """

    resamples: int = Field(default=1000, ge=100)
    permutations: int = Field(default=1000, ge=0)
    confidence: float = Field(default=0.95, gt=0, lt=1)
    seed: int = Field(default=0, ge=0)

    def generator(self, *key: str) -> np.random.Generator:
        return np.random.default_rng([self.seed, int(content_hash(list(key))[:15], 16)])


class Estimate(FrozenModel):
    """A point estimate with its bootstrap interval, when one can be computed."""

    value: float
    lower: float | None
    upper: float | None


@dataclass(frozen=True)
class CaseSample:
    """One task case's statistic and its bootstrap replicates; NaN marks undefined values."""

    value: float
    replicates: FloatArray


@dataclass(frozen=True)
class ComparisonSample:
    within: CaseSample
    between: CaseSample
    excess: CaseSample


def summarize(
    samples: Sequence[CaseSample], inference: Inference, rng: np.random.Generator
) -> Estimate | None:
    """Average a statistic over task cases and attach a case-resampled percentile interval."""
    values = np.array([sample.value for sample in samples], dtype=np.float64)
    defined = ~np.isnan(values)
    if not defined.any():
        return None
    stacked = np.vstack([sample.replicates for sample in samples])
    picks = rng.integers(0, len(samples), size=(inference.resamples, len(samples)))
    drawn = stacked[picks, np.arange(inference.resamples)[:, np.newaxis]]
    return interval(float(values[defined].mean()), _row_means(drawn), inference)


def interval(value: float, replicates: FloatArray, inference: Inference) -> Estimate:
    """A point estimate with the percentile interval of its defined bootstrap replicates."""
    finite = replicates[~np.isnan(replicates)]
    if finite.size == 0:
        return Estimate(value=value, lower=None, upper=None)
    tail = (1.0 - inference.confidence) / 2.0
    lower, upper = np.quantile(finite, [tail, 1.0 - tail])
    return Estimate(value=value, lower=float(lower), upper=float(upper))


def sample_values(values: FloatArray, inference: Inference, rng: np.random.Generator) -> CaseSample:
    """Mean of per-observation values in one case, with repetition-resampled replicates."""
    draws = rng.integers(0, values.size, size=(inference.resamples, values.size))
    return CaseSample(value=float(values.mean()), replicates=values[draws].mean(axis=1))


def sample_repeated(
    matrix: FloatArray, inference: Inference, rng: np.random.Generator
) -> ComparisonSample:
    """A variant compared with itself: the change between equals the variation within."""
    draws = rng.integers(0, matrix.shape[0], size=(inference.resamples, matrix.shape[0]))
    sums, counts = _distinct_pair_sums(matrix, draws)
    within = CaseSample(value=_mean_or_nan(_upper(matrix)), replicates=_ratio(sums, counts))
    excess = CaseSample(
        value=float("nan") if math.isnan(within.value) else 0.0,
        replicates=np.where(np.isnan(within.replicates), np.nan, 0.0),
    )
    return ComparisonSample(within=within, between=within, excess=excess)


def sample_transition(
    start: FloatArray,
    end: FloatArray,
    cross: FloatArray,
    inference: Inference,
    rng: np.random.Generator,
) -> ComparisonSample:
    """Variation within both conditions, pooled, and the change between them.

    ``start`` and ``end`` are symmetric within-variant difference matrices with undefined
    diagonals; ``cross[i, j]`` compares start repetition ``i`` with end repetition ``j``.
    """
    start_draws = rng.integers(0, start.shape[0], size=(inference.resamples, start.shape[0]))
    end_draws = rng.integers(0, end.shape[0], size=(inference.resamples, end.shape[0]))
    start_sums, start_counts = _distinct_pair_sums(start, start_draws)
    end_sums, end_counts = _distinct_pair_sums(end, end_draws)
    within = CaseSample(
        value=_mean_or_nan(np.concatenate([_upper(start), _upper(end)])),
        replicates=_ratio(start_sums + end_sums, start_counts + end_counts),
    )
    resampled_cross = cross[start_draws[:, :, np.newaxis], end_draws[:, np.newaxis, :]]
    between = CaseSample(value=float(cross.mean()), replicates=resampled_cross.mean(axis=(1, 2)))
    excess = CaseSample(
        value=between.value - within.value,
        replicates=between.replicates - within.replicates,
    )
    return ComparisonSample(within=within, between=between, excess=excess)


def permutation_p_value(
    matrices: Sequence[FloatArray],
    splits: Sequence[int],
    inference: Inference,
    rng: np.random.Generator,
) -> float | None:
    """One-sided permutation p-value of the mean excess change over cases.

    ``matrices[k]`` holds the differences between every pair of case ``k``'s outputs: the
    first ``splits[k]`` outputs come from one condition and the rest from the other. The
    diagonal is undefined. Outputs are shuffled between conditions within each case.
    """
    if inference.permutations == 0:
        return None
    observed: list[float] = []
    permuted: list[FloatArray] = []
    for matrix, split in zip(matrices, splits, strict=True):
        size = matrix.shape[0]
        if _within_pairs(split, size - split) == 0:
            continue
        identity: IntArray = np.arange(size, dtype=np.int64)[np.newaxis, :]
        observed.append(float(_excess(matrix, identity, split)[0]))
        orders = rng.permuted(
            np.tile(np.arange(size, dtype=np.int64), (inference.permutations, 1)), axis=1
        )
        permuted.append(_excess(matrix, orders, split))
    if not observed:
        return None
    statistic = float(np.mean(observed))
    null = np.mean(np.vstack(permuted), axis=0)
    exceed = int(np.count_nonzero(null >= statistic - TOLERANCE))
    return (1 + exceed) / (1 + inference.permutations)


def holm(p_values: Sequence[float | None]) -> list[float | None]:
    """Holm's correction for testing several p-values together; undefined values stay undefined."""
    defined = sorted((value, index) for index, value in enumerate(p_values) if value is not None)
    adjusted: list[float | None] = [None] * len(p_values)
    running = 0.0
    for rank, (value, index) in enumerate(defined):
        running = max(running, min(1.0, (len(defined) - rank) * value))
        adjusted[index] = running
    return adjusted


def rank_correlation(first: Sequence[float], second: Sequence[float]) -> float | None:
    """Spearman rank correlation, with ties sharing their average rank; undefined if constant."""
    if len(first) != len(second) or len(first) < 3:
        return None
    left, right = _ranks(np.asarray(first)), _ranks(np.asarray(second))
    if left.std() == 0 or right.std() == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def _excess(matrix: FloatArray, orders: IntArray, split: int) -> FloatArray:
    first, second = orders[:, :split], orders[:, split:]
    cross = matrix[first[:, :, np.newaxis], second[:, np.newaxis, :]].mean(axis=(1, 2))
    within = _block_sum(matrix, first) + _block_sum(matrix, second)
    return cross - within / _within_pairs(split, matrix.shape[0] - split)


def _block_sum(matrix: FloatArray, members: IntArray) -> FloatArray:
    block = matrix[members[:, :, np.newaxis], members[:, np.newaxis, :]]
    return np.nansum(block, axis=(1, 2)) / 2.0


def _within_pairs(first: int, second: int) -> int:
    return first * (first - 1) // 2 + second * (second - 1) // 2


def _ranks(values: FloatArray) -> FloatArray:
    order = values.argsort(kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    ranks[order] = np.arange(values.size, dtype=np.float64)
    for value in np.unique(values):
        tied = values == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def _distinct_pair_sums(matrix: FloatArray, draws: IntArray) -> tuple[FloatArray, IntArray]:
    size = matrix.shape[0]
    upper = np.triu(np.ones((size, size), dtype=bool), k=1)
    left = draws[:, :, np.newaxis]
    right = draws[:, np.newaxis, :]
    mask = upper & (left != right)
    sums = np.where(mask, matrix[left, right], 0.0).sum(axis=(1, 2))
    return sums, mask.sum(axis=(1, 2))


def _upper(matrix: FloatArray) -> FloatArray:
    return matrix[np.triu_indices(matrix.shape[0], k=1)]


def _mean_or_nan(values: FloatArray) -> float:
    return float(values.mean()) if values.size else float("nan")


def _ratio(sums: FloatArray, counts: IntArray) -> FloatArray:
    safe = np.maximum(counts, 1)
    return np.where(counts > 0, sums / safe, np.nan)


def _row_means(values: FloatArray) -> FloatArray:
    defined = ~np.isnan(values)
    counts = defined.sum(axis=1)
    sums = np.where(defined, values, 0.0).sum(axis=1)
    return _ratio(sums, counts)
