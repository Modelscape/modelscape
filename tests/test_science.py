from __future__ import annotations

import random
import threading
from collections.abc import Callable

import numpy as np
import pytest

from modelscape import (
    CallableTarget,
    ExecutionConfig,
    Experiment,
    Inference,
    Results,
    Runner,
    TargetOutput,
    TargetRequest,
)
from modelscape.analysis.statistics import CaseSample, summarize
from modelscape.core.observations import Usage
from modelscape.measures import ExactMatch, TokenJaccardDistance
from tests.helpers import Probe, case_index, level, level_space, probe_cases

SETTINGS = Inference(resamples=2000, seed=11)
WORDS = ("alpha", "beta", "gamma", "delta")


async def run(
    answer: Callable[[TargetRequest], str | TargetOutput],
    *,
    name: str = "target",
    repetitions: int = 6,
    cases: dict[str, Probe] | None = None,
) -> Results:
    experiment = Experiment(
        task_space=level_space(cases),
        targets=[CallableTarget(answer, name=name)],
        repetitions=repetitions,
        point_metrics=[ExactMatch()],
        difference_measures=[TokenJaccardDistance()],
        execution=ExecutionConfig(concurrency=1),
    )
    return await Runner().run(experiment)


def shifted(probability: float) -> Callable[[TargetRequest], str]:
    def answer(request: TargetRequest) -> str:
        rng = random.Random(request.seed)
        if level(request) >= 2 and rng.random() < probability:
            return f"refused {rng.choice(['now', 'today'])}"
        return f"stable {rng.choice(['answer', 'reply'])}"

    return answer


def heterogeneous(request: TargetRequest) -> str:
    words: list[str] = list(WORDS)
    if level(request) >= 1:
        for position in range(case_index(request) + 1):
            words[position] = f"changed{position}"
    return " ".join(words)


async def test_analysis_is_valid_when_the_target_ignores_seeds() -> None:
    hidden = random.Random(5)
    lock = threading.Lock()

    def unseeded(request: TargetRequest) -> str:
        with lock:
            draw = hidden.random()
            word = hidden.choice(["answer", "reply"])
        if level(request) >= 2 and draw < 0.9:
            return f"refused {word}"
        return f"stable {word}"

    results = await run(unseeded, repetitions=8)
    profile = results.profile("level", "token_jaccard", inference=SETTINGS)
    step = profile.local[1]
    assert step.excess is not None
    assert step.excess.lower is not None
    assert step.excess.lower > 0
    assert [
        (c.transition.start_value, c.transition.end_value) for c in profile.candidate_boundaries
    ] == [(1, 2)]


async def test_text_only_outputs_and_missing_metadata_give_identical_science() -> None:
    plain = shifted(0.8)

    def rich(request: TargetRequest) -> TargetOutput:
        return TargetOutput(
            text=plain(request),
            metadata={"provider": "fixture", "region": "eu"},
            usage=Usage(input_tokens=12, output_tokens=4, cost=0.001),
        )

    bare = await run(plain)
    detailed = await run(rich)
    first = bare.profile("level", "token_jaccard", inference=SETTINGS)
    second = detailed.profile("level", "token_jaccard", inference=SETTINGS)
    assert [t.row() for t in first.local] == [t.row() for t in second.local]
    assert [t.row() for t in first.baseline] == [t.row() for t in second.baseline]
    assert first.metric_table() == second.metric_table()


async def test_repetitions_do_not_multiply_independent_cases() -> None:
    few = await run(heterogeneous, repetitions=3)
    many = await run(heterogeneous, repetitions=12)
    narrow = few.profile("level", "token_jaccard", inference=SETTINGS).baseline[1]
    wide = many.profile("level", "token_jaccard", inference=SETTINGS).baseline[1]
    assert narrow.cases == wide.cases == 3
    assert wide.observations == 4 * narrow.observations
    assert narrow.excess is not None
    assert wide.excess is not None
    assert [item.excess for item in wide.per_case] == pytest.approx([0.4, 2 / 3, 6 / 7])
    for estimate in (narrow.excess, wide.excess):
        assert estimate.lower == pytest.approx(0.4, abs=0.02)
        assert estimate.upper == pytest.approx(6 / 7, abs=0.02)


def test_pairwise_comparisons_are_not_bootstrap_units() -> None:
    rng = np.random.default_rng(0)
    values = [0.1, 0.5, 0.9]
    samples = [CaseSample(value=v, replicates=np.full(SETTINGS.resamples, v)) for v in values]
    estimate = summarize(samples, SETTINGS, rng)
    assert estimate is not None
    means = np.array(values)[rng.integers(0, 3, size=(SETTINGS.resamples, 3))].mean(axis=1)
    assert estimate.value == pytest.approx(0.5)
    assert estimate.lower == pytest.approx(float(np.quantile(means, 0.025)), abs=0.05)
    assert estimate.upper == pytest.approx(float(np.quantile(means, 0.975)), abs=0.05)


async def test_matched_cases_stay_paired() -> None:
    def vocabulary(request: TargetRequest) -> str:
        rng = random.Random(request.seed)
        return f"topic{case_index(request)} {rng.choice(['short', 'brief'])}"

    results = await run(vocabulary)
    transition = results.profile("level", "token_jaccard", inference=SETTINGS).local[1]
    assert transition.between is not None
    assert transition.excess is not None
    assert transition.between.value < 0.7
    assert abs(transition.excess.value) < 0.1


async def test_identical_distributions_give_excess_near_zero() -> None:
    results = await run(shifted(0.0), repetitions=10, cases=probe_cases(6))
    for transition in results.profile("level", "token_jaccard", inference=SETTINGS).local:
        assert transition.excess is not None
        assert transition.excess.lower is not None
        assert transition.excess.upper is not None
        assert abs(transition.excess.value) < 0.06
        assert transition.excess.lower <= 0 <= transition.excess.upper


async def test_deliberate_shifts_give_positive_excess_ordered_by_strength() -> None:
    weak = await run(shifted(0.3), repetitions=10, cases=probe_cases(6))
    strong = await run(shifted(0.9), repetitions=10, cases=probe_cases(6))
    weak_step = weak.profile("level", "token_jaccard", inference=SETTINGS).local[1]
    strong_step = strong.profile("level", "token_jaccard", inference=SETTINGS).local[1]
    assert weak_step.excess is not None
    assert strong_step.excess is not None
    assert weak_step.excess.value > 0
    assert strong_step.excess.lower is not None
    assert strong_step.excess.lower > 0
    assert strong_step.excess.value > weak_step.excess.value


async def test_single_case_profiles_resample_repetitions_explicitly() -> None:
    results = await run(shifted(0.9), cases=probe_cases(1))
    profile = results.profile("level", "token_jaccard", inference=SETTINGS)
    assert {t.sampling_unit for t in profile.local} == {"repetition"}
    assert {p.sampling_unit for p in profile.metrics} == {"repetition"}
    assert profile.local[1].excess is not None
    assert profile.local[1].excess.lower is not None
