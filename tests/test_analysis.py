from __future__ import annotations

import random
from collections.abc import Sequence

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from modelscape import (
    Axis,
    BoundaryCriterion,
    ExecutionConfig,
    Experiment,
    Grid,
    Inference,
    Results,
    RetryPolicy,
    Runner,
    Sweep,
    TaskSpace,
)
from modelscape.analysis.robustness import compare_measures
from modelscape.analysis.statistics import (
    holm,
    permutation_p_value,
    rank_correlation,
    sample_repeated,
    sample_transition,
    summarize,
)
from modelscape.core import AnalysisError, Coordinate, StoreError
from modelscape.core.experiments import RunManifest
from modelscape.measures import (
    DifferenceMeasure,
    ExactMatch,
    NormalizedEditDistance,
    TokenJaccardDistance,
)
from modelscape.storage import MemoryStore
from modelscape.targets import CallableTarget, Target, TargetRequest
from tests.helpers import (
    Probe,
    level,
    level_space,
    noisy_threshold_target,
    payload,
    probe_cases,
    set_level,
    set_notes,
    threshold_target,
)

SETTINGS = Inference(resamples=200, seed=3)


async def run(
    *targets: Target,
    repetitions: int = 4,
    grid: bool = False,
    store: MemoryStore | None = None,
    measures: Sequence[DifferenceMeasure] = (TokenJaccardDistance(),),
) -> Results:
    experiment = Experiment(
        task_space=level_space(),
        targets=list(targets),
        repetitions=repetitions,
        point_metrics=[ExactMatch()],
        difference_measures=measures,
        design=Grid() if grid else Sweep(),
        execution=ExecutionConfig(concurrency=8, retry=RetryPolicy(max_attempts=1)),
    )
    return await Runner(store=store).run(experiment)


@given(
    st.floats(min_value=0, max_value=1),
    st.floats(min_value=0, max_value=1),
    st.integers(2, 6),
    st.integers(2, 6),
)
def test_constant_matrices_give_exact_estimates(
    within: float, between: float, first: int, second: int
) -> None:
    rng = np.random.default_rng(0)
    start = np.full((first, first), within)
    end = np.full((second, second), within)
    np.fill_diagonal(start, np.nan)
    np.fill_diagonal(end, np.nan)
    sample = sample_transition(start, end, np.full((first, second), between), SETTINGS, rng)
    estimate = summarize([sample.excess], SETTINGS, rng)
    assert estimate is not None
    assert estimate.value == pytest.approx(between - within)
    assert estimate.lower == pytest.approx(between - within)
    assert estimate.upper == pytest.approx(between - within)


def test_resampled_pairs_never_compare_a_run_with_itself() -> None:
    matrix = np.array([[np.nan, 0.5], [0.5, np.nan]])
    sample = sample_repeated(matrix, SETTINGS, np.random.default_rng(1))
    defined = sample.within.replicates[~np.isnan(sample.within.replicates)]
    assert defined.size > 0
    assert np.all(defined == 0.5)
    assert np.isnan(sample.within.replicates).any()


async def test_local_profile_separates_controlled_change_from_noise() -> None:
    results = await run(threshold_target())
    profile = results.profile(
        "level", "token_jaccard", criterion=BoundaryCriterion(min_excess=0.5), inference=SETTINGS
    )
    assert [(t.start_value, t.end_value) for t in profile.local] == [(0, 1), (1, 2), (2, 3)]
    assert [t.between.value for t in profile.local if t.between] == [0.0, 1.0, 0.0]
    assert all(t.within is not None and t.within.value == 0.0 for t in profile.local)
    assert all(t.ratio is None for t in profile.local)
    assert [
        (c.transition.start_value, c.transition.end_value) for c in profile.candidate_boundaries
    ] == [(1, 2)]
    assert "is above 0.500" in profile.candidate_boundaries[0].rationale
    transition = profile.local[1]
    assert transition.cases == 3
    assert transition.observations == 3 * 2 * 4
    assert transition.sampling_unit == "case"
    assert [item.case for item in transition.per_case] == ["case-0", "case-1", "case-2"]
    assert all(item.excess == 1.0 for item in transition.per_case)


async def test_baseline_profile_starts_at_the_noise_floor() -> None:
    results = await run(noisy_threshold_target())
    profile = results.profile("level", "token_jaccard", inference=SETTINGS)
    at_baseline = profile.baseline[0]
    assert at_baseline.start == at_baseline.end
    assert at_baseline.between == at_baseline.within
    assert at_baseline.excess is not None
    assert at_baseline.excess.value == 0.0
    shifted = profile.baseline[2]
    assert shifted.between is not None
    assert shifted.within is not None
    assert shifted.between.value > shifted.within.value
    assert shifted.ratio == pytest.approx(shifted.between.value / shifted.within.value)
    assert shifted.excess is not None
    assert shifted.excess.lower is not None
    assert shifted.excess.lower > 0


async def test_point_metrics_are_reported_separately() -> None:
    results = await run(threshold_target())
    profile = results.profile("level", "token_jaccard", inference=SETTINGS)
    assert [point.estimate.value for point in profile.metrics] == [1.0, 1.0, 0.0, 0.0]
    assert {str(row["metric"]) for row in profile.metric_table()} == {"exact_match"}
    assert {str(row["view"]) for row in profile.table()} == {"local", "baseline"}


async def test_bootstrap_intervals_are_deterministic_given_a_seed() -> None:
    results = await run(noisy_threshold_target())
    first = results.profile("level", "token_jaccard", inference=Inference(seed=1))
    again = results.profile("level", "token_jaccard", inference=Inference(seed=1))
    other = results.profile("level", "token_jaccard", inference=Inference(seed=2))
    assert first == again
    assert first.local[1].excess != other.local[1].excess


async def test_single_repetitions_leave_noise_undefined() -> None:
    results = await run(threshold_target(), repetitions=1)
    profile = results.profile("level", "token_jaccard", inference=SETTINGS)
    assert profile.local[1].between is not None
    assert profile.local[1].within is None
    assert profile.local[1].excess is None
    assert profile.baseline[0].between is None
    assert profile.candidate_boundaries == ()


async def test_nominal_axes_have_baseline_but_no_local_view() -> None:
    results = await run(threshold_target())
    profile = results.profile("style", "token_jaccard", inference=SETTINGS)
    assert profile.local == ()
    assert len(profile.baseline) == 2


async def test_profiles_away_from_baseline_require_evaluated_coordinates() -> None:
    sweep = await run(threshold_target())
    with pytest.raises(AnalysisError, match="Grid design"):
        sweep.profile("level", "token_jaccard", fixed={"style": "formal"})
    grid = await run(threshold_target(), grid=True)
    profile = grid.profile("level", "token_jaccard", fixed={"style": "formal"}, inference=SETTINGS)
    assert profile.fixed == Coordinate({"style": "formal"})
    assert profile.baseline[0].start == grid.experiment.space.baseline


async def test_local_transitions_peak_where_neighbors_change_beyond_noise() -> None:
    space = TaskSpace(
        cases=probe_cases(),
        axes=[
            Axis(Probe.level, (0, 1, 2, 3), via=set_level, scale="numeric"),
            Axis(Probe.note_count, (0, 1), via=set_notes, scale="numeric"),
        ],
    )
    experiment = Experiment(
        task_space=space,
        targets=[noisy_threshold_target()],
        repetitions=4,
        difference_measures=[TokenJaccardDistance()],
        design=Grid(),
    )
    results = await Runner().run(experiment)
    steps = {
        (transition.start_value, transition.end_value): transition
        for transition in results.transitions("token_jaccard", inference=SETTINGS)
        if transition.axis == "level" and transition.start["note_count"] == 0
    }
    quiet, edge = steps[(0, 1)].excess, steps[(1, 2)].excess
    assert quiet is not None
    assert edge is not None
    assert quiet.value == pytest.approx(0.0, abs=0.05)
    assert edge.value > quiet.value + 0.1
    assert steps[(1, 2)].measurement_ids


async def test_every_aggregate_traces_back_to_observations() -> None:
    results = await run(noisy_threshold_target())
    transition = results.profile("level", "token_jaccard", inference=SETTINGS).local[1]
    trace = results.trace(transition)
    assert len(trace.difference_measurements) == len(transition.measurement_ids) == 3 * (16 + 12)
    assert len(trace.observations) == transition.observations
    assert {o.coordinate for o in trace.observations} == {transition.start, transition.end}
    assert {v.coordinate for v in trace.variants} == {transition.start, transition.end}
    point = results.profile("level", "token_jaccard", inference=SETTINGS).metrics[0]
    assert len(results.trace(point).point_measurements) == point.observations


async def test_results_reload_identically_from_a_store() -> None:
    store = MemoryStore()
    results = await run(noisy_threshold_target(), store=store)
    loaded = Results.load(store, results.experiment.id)
    assert loaded.observations == results.observations
    assert loaded.profile("level", "token_jaccard") == results.profile("level", "token_jaccard")


async def test_variability_and_transitions_cover_all_variants_and_neighbors() -> None:
    results = await run(noisy_threshold_target(), grid=True)
    variability = results.variability("token_jaccard", inference=SETTINGS)
    assert len(variability) == len(results.variants)
    assert all(item.repetitions == 4 for item in variability)
    transitions = results.transitions("token_jaccard", inference=SETTINGS)
    assert len(transitions) == 3 * 2
    assert all(t.axis == "level" for t in transitions)


async def test_multiple_targets_require_explicit_selection() -> None:
    results = await run(threshold_target("a"), noisy_threshold_target("b"))
    with pytest.raises(AnalysisError, match="pass target="):
        results.profile("level", "token_jaccard")
    profiles = results.profiles("level", "token_jaccard", inference=SETTINGS)
    assert [profile.target for profile in profiles] == ["a", "b"]
    with pytest.raises(AnalysisError, match="Unknown difference measure"):
        results.profile("level", "missing", target="a")


def distances(points: np.ndarray) -> np.ndarray:
    matrix = np.abs(points[:, np.newaxis] - points[np.newaxis, :])
    np.fill_diagonal(matrix, np.nan)
    return matrix


def test_permutation_p_values_are_calibrated_and_sensitive() -> None:
    rng = np.random.default_rng(4)
    settings = Inference(permutations=199, seed=0)
    null = [
        permutation_p_value([distances(rng.normal(size=12))], [6], settings, rng)
        for _ in range(200)
    ]
    shifted = permutation_p_value(
        [distances(np.concatenate([rng.normal(size=6), rng.normal(3, 1, size=6)]))],
        [6],
        settings,
        rng,
    )
    assert all(value is not None for value in null)
    assert np.mean([value is not None and value <= 0.05 for value in null]) < 0.1
    assert shifted is not None
    assert shifted <= 0.01
    assert permutation_p_value([distances(np.zeros(2))], [1], settings, rng) is None
    assert (
        permutation_p_value([distances(np.zeros(4))], [2], Inference(permutations=0), rng) is None
    )


def test_holm_adjusts_a_family_and_keeps_undefined_values() -> None:
    assert holm([0.01, 0.04, None, 0.03]) == pytest.approx([0.03, 0.06, None, 0.06])
    assert holm([]) == []
    assert holm([0.6, 0.7]) == pytest.approx([1.0, 1.0])


def test_rank_correlation_uses_ranks_and_needs_variation() -> None:
    assert rank_correlation([1, 2, 3, 4], [10, 20, 30, 400]) == pytest.approx(1.0)
    assert rank_correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert rank_correlation([1, 1, 2], [5, 5, 9]) == pytest.approx(1.0)
    assert rank_correlation([1, 2, 3], [4, 4, 4]) is None
    assert rank_correlation([1, 2], [1, 2]) is None


async def test_transitions_carry_permutation_p_values() -> None:
    results = await run(noisy_threshold_target(), repetitions=6)
    profile = results.profile("level", "token_jaccard", inference=SETTINGS)
    p_values = [transition.p_value for transition in profile.local]
    assert all(value is not None for value in p_values)
    assert p_values[1] is not None
    assert p_values[1] < 0.01
    assert profile.candidate_boundaries[0].adjusted_p_value >= p_values[1]
    silent = results.profile("level", "token_jaccard", inference=Inference(permutations=0))
    assert all(transition.p_value is None for transition in silent.local)
    assert silent.candidate_boundaries == ()
    assert "p_value" in profile.table()[0]


async def test_axes_are_ranked_by_sensitivity() -> None:
    results = await run(noisy_threshold_target(), repetitions=6)
    ranked = results.sensitivity(
        "token_jaccard", criterion=BoundaryCriterion(min_excess=0.25), inference=SETTINGS
    )
    assert [item.axis for item in ranked] == ["level", "style"]
    assert ranked[0].peak is not None
    assert (ranked[0].peak.start_value, ranked[0].peak.end_value) == (1, 2)
    assert ranked[0].boundaries == 1
    assert ranked[1].boundaries == 0
    assert ranked[1].max_excess is not None
    assert ranked[0].max_excess is not None
    assert ranked[1].max_excess < ranked[0].max_excess


async def test_nominal_axes_find_boundaries_against_the_baseline() -> None:
    def answer(request: TargetRequest) -> str:
        noise = random.Random(request.seed).choice(["", " indeed"])
        return f"{payload(request)['tone']} answer{noise}"

    results = await run(
        CallableTarget(answer, name="styled"),
        measures=[TokenJaccardDistance(), NormalizedEditDistance()],
    )
    profile = results.profile("style", "token_jaccard", inference=SETTINGS)
    assert profile.local == ()
    assert [step.end_value for step in profile.steps] == ["formal"]
    assert [item.transition.end_value for item in profile.candidate_boundaries] == ["formal"]
    (agreement,) = results.agreement(inference=SETTINGS)
    assert agreement.transitions == 4
    assert agreement.boundary_overlap == 1.0


def test_agreement_without_shared_transitions_is_undefined() -> None:
    agreement = compare_measures("model", ("first", "second"), ((), ()), BoundaryCriterion())
    assert (agreement.transitions, agreement.rank_correlation, agreement.boundary_overlap) == (
        0,
        None,
        None,
    )


async def test_complementary_measures_are_checked_for_agreement() -> None:
    results = await run(
        noisy_threshold_target(),
        repetitions=6,
        measures=[TokenJaccardDistance(), NormalizedEditDistance()],
    )
    (agreement,) = results.agreement(inference=SETTINGS)
    assert (agreement.first, agreement.second) == ("token_jaccard", "edit_distance")
    assert agreement.transitions == 4
    assert agreement.rank_correlation == pytest.approx(1.0)
    assert agreement.boundary_overlap == 1.0
    with pytest.raises(AnalysisError, match="Unknown difference measure"):
        results.agreement(["token_jaccard", "missing"])


async def test_observations_are_selected_by_target_case_and_coordinate() -> None:
    results = await run(threshold_target("a"), noisy_threshold_target("b"), repetitions=2)
    selected = results.select(target="b", case="case-1", coordinate={"level": 2})
    assert len(selected) == 2
    assert {o.target.name for o in selected} == {"b"}
    assert {o.coordinate for o in selected} == {Coordinate({"level": 2, "style": "plain"})}
    assert len(results.select(target="a")) == len(results.observations) // 2


async def test_unknown_targets_and_cases_are_refused() -> None:
    results = await run(threshold_target())
    with pytest.raises(AnalysisError, match="Unknown target 'missing'"):
        results.profile("level", "token_jaccard", target="missing")
    with pytest.raises(AnalysisError, match=r"unknown: \['missing'\]"):
        results.profile("level", "token_jaccard", cases=["case-0", "missing"])
    with pytest.raises(AnalysisError, match="non-empty subset"):
        results.profile("level", "token_jaccard", cases=[])
    profile = results.profile("level", "token_jaccard", cases=["case-1"], inference=SETTINGS)
    assert [item.case for item in profile.local[1].per_case] == ["case-1"]


async def test_loading_from_an_incomplete_store_names_what_is_missing() -> None:
    store = MemoryStore()
    results = await run(threshold_target(), store=store)
    with pytest.raises(StoreError, match="no ExperimentRecord with id 'missing'"):
        Results.load(store, "missing")
    manifest = store.get(RunManifest, [results.experiment.id])[results.experiment.id]
    partial = MemoryStore()
    partial.put([results.experiment, manifest, *results.variants])
    with pytest.raises(StoreError, match=r"missing \d+ Observation records"):
        Results.load(partial, results.experiment.id)


def failing_from(threshold: int, share: float) -> CallableTarget:
    def answer(request: TargetRequest) -> str:
        if level(request) >= threshold and random.Random(request.seed).random() < share:
            raise ConnectionError("provider unavailable")
        return "stable"

    return CallableTarget(answer, name="failing")


async def test_analysis_uses_only_successful_observations() -> None:
    results = await run(failing_from(2, 0.5), repetitions=8)
    failed = {o.id for o in results.failures}
    assert failed
    profile = results.profile("level", "token_jaccard", inference=SETTINGS)
    transition = profile.local[1]
    trace = results.trace(transition)
    assert not failed & {o.id for o in trace.observations}
    assert transition.observations == len(trace.observations) < 3 * 2 * 8
    assert transition.excess is not None
    assert transition.excess.value == 0.0


async def test_a_coordinate_without_successful_observations_cannot_be_profiled() -> None:
    results = await run(failing_from(2, 1.0))
    assert {o.coordinate["level"] for o in results.failures} == {2, 3}
    with pytest.raises(AnalysisError, match="no successful observations at both"):
        results.profile("level", "token_jaccard")
    empty = [
        (item.repetitions, item.within)
        for item in results.variability("token_jaccard", inference=SETTINGS)
        if item.coordinate["level"] in {2, 3}
    ]
    assert empty == [(0, None)] * 6
