from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from modelscape import ExecutionConfig, Experiment, Grid, RetryPolicy, Runner, Sweep
from modelscape.core import (
    ExperimentError,
    Identity,
    MeasureError,
    MeasureValue,
    Observation,
    TargetOutput,
)
from modelscape.execution import Progress
from modelscape.execution.jobs import ObservationJob, redact_credentials, schedule
from modelscape.measures import DifferenceMeasure, ExactMatch, Response, TokenJaccardDistance
from modelscape.storage import MemoryStore, SQLiteStore
from modelscape.targets import CallableTarget, Target, TargetRequest
from tests.helpers import (
    FAST,
    level_space,
    noisy_threshold_target,
    threshold_answer,
    threshold_target,
)


class SimulatedInterruptError(Exception):
    pass


class CountingTarget:
    def __init__(self, name: str = "counting", fail_first: int = 0) -> None:
        self.calls = 0
        self.fail_first = fail_first
        self._identity = Identity(name=name)

    @property
    def identity(self) -> Identity:
        return self._identity

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        self.calls += 1
        await asyncio.sleep(0)
        if self.calls <= self.fail_first:
            raise ConnectionError("temporary outage")
        return TargetOutput(text=threshold_answer(request))


class CountingMeasure:
    def __init__(self) -> None:
        self.pairs = 0

    @property
    def identity(self) -> Identity:
        return Identity(name="counting_measure")

    async def compare(self, pairs: Sequence[tuple[Response, Response]]) -> Sequence[MeasureValue]:
        self.pairs += len(pairs)
        return [MeasureValue(value=float(a.output.text != b.output.text)) for a, b in pairs]


def build(
    target: Target,
    *,
    repetitions: int = 3,
    measures: Sequence[DifferenceMeasure] | None = None,
    execution: ExecutionConfig = FAST,
    seed: int = 0,
) -> Experiment:
    return Experiment(
        task_space=level_space(),
        targets=[target],
        repetitions=repetitions,
        point_metrics=[ExactMatch()],
        difference_measures=measures if measures is not None else [TokenJaccardDistance()],
        execution=execution,
        seed=seed,
    )


async def test_runner_executes_every_repetition_and_measures_them() -> None:
    results = await Runner().run(build(threshold_target()))
    space = level_space()
    assert len(results.variants) == len(space.cases) * len(space.sweep())
    assert len(results.observations) == len(results.variants) * 3
    assert len({observation.id for observation in results.observations}) == len(
        results.observations
    )
    assert len(results.point_measurements) == len(results.observations)
    assert all(observation.succeeded for observation in results.observations)
    assert all(
        observation.output.duration_seconds is not None for observation in results.observations
    )


async def test_identities_are_deterministic_and_seed_dependent() -> None:
    first = await Runner().run(build(noisy_threshold_target()))
    second = await Runner().run(build(noisy_threshold_target()))
    reseeded = await Runner().run(build(noisy_threshold_target(), seed=1))
    assert first.experiment.id == second.experiment.id != reseeded.experiment.id
    assert [o.id for o in first.observations] == [o.id for o in second.observations]
    assert [o.output.text for o in first.observations] == [
        o.output.text for o in second.observations
    ]
    assert {o.id for o in first.observations}.isdisjoint({o.id for o in reseeded.observations})


async def test_rerunning_with_a_store_reuses_observations_and_measurements() -> None:
    store = MemoryStore()
    target = CountingTarget()
    measure = CountingMeasure()
    first = await Runner(store=store).run(build(target, measures=[measure]))
    calls, pairs = target.calls, measure.pairs
    second = await Runner(store=store).run(build(target, measures=[measure]))
    assert (target.calls, measure.pairs) == (calls, pairs)
    assert first.observations == second.observations
    assert first.difference_measurements == second.difference_measurements


async def test_more_repetitions_only_add_new_observations() -> None:
    store = MemoryStore()
    target = CountingTarget()
    await Runner(store=store).run(build(target, repetitions=2))
    before = target.calls
    results = await Runner(store=store).run(build(target, repetitions=3))
    assert target.calls - before == len(results.variants)


@settings(
    max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.integers(min_value=0, max_value=40), st.integers(min_value=1, max_value=4))
def test_interrupted_runs_resume_without_duplicating_observations(
    tmp_path: Path, interrupt_after: int, concurrency: int
) -> None:
    path = tmp_path / f"resume-{interrupt_after}-{concurrency}.db"
    path.unlink(missing_ok=True)
    target = CountingTarget()
    execution = ExecutionConfig(concurrency=concurrency, retry=RetryPolicy(max_attempts=1))
    spec = build(target, execution=execution)
    total = len(level_space().cases) * len(level_space().sweep()) * spec.repetitions

    def interrupt(progress: Progress) -> None:
        if progress.completed - progress.reused >= interrupt_after and progress.completed < total:
            raise SimulatedInterruptError

    with SQLiteStore(path) as store, pytest.raises(SimulatedInterruptError):
        asyncio.run(Runner(store=store, on_progress=interrupt).run(spec))
    calls_before_resume = target.calls
    with SQLiteStore(path) as store:
        results = asyncio.run(Runner(store=store).run(spec))
    assert len(results.observations) == total
    assert len({observation.id for observation in results.observations}) == total
    assert target.calls - calls_before_resume <= total - min(interrupt_after, total)


async def test_transient_failures_are_retried() -> None:
    target = CountingTarget(fail_first=2)
    execution = ExecutionConfig(
        concurrency=1, retry=RetryPolicy(max_attempts=3, initial_delay_seconds=0)
    )
    results = await Runner().run(build(target, repetitions=1, execution=execution))
    assert results.failures == ()
    first = min(results.observations, key=lambda observation: observation.schedule_position)
    assert first.attempts == 3


async def test_exhausted_retries_and_timeouts_become_structured_errors() -> None:
    async def slow(request: TargetRequest) -> str:
        await asyncio.sleep(1)
        return "late"

    execution = ExecutionConfig(
        timeout_seconds=0.01, retry=RetryPolicy(max_attempts=2, initial_delay_seconds=0)
    )
    results = await Runner().run(
        build(CallableTarget(slow, name="slow"), repetitions=1, execution=execution)
    )
    assert len(results.failures) == len(results.observations)
    error = results.failures[0].output.error
    assert error is not None
    assert error.type == "TimeoutError"
    assert "Timed out after 0.01 seconds" in error.message
    assert results.failures[0].attempts == 2
    assert results.difference_measurements == ()


async def test_failed_observations_are_retried_on_the_next_run() -> None:
    store = MemoryStore()
    broken = CountingTarget(fail_first=10_000)
    await Runner(store=store).run(build(broken, repetitions=1))
    healed = CountingTarget()
    results = await Runner(store=store).run(build(healed, repetitions=1))
    assert healed.calls == len(results.observations)
    assert results.failures == ()


async def test_error_messages_never_store_credentials() -> None:
    def leak(request: TargetRequest) -> str:
        raise PermissionError(
            "denied: Authorization: Bearer abc.def-123 api_key=hunter2 key sk-live1234567890"
        )

    execution = ExecutionConfig(retry=RetryPolicy(max_attempts=1))
    results = await Runner().run(
        build(CallableTarget(leak, name="leak"), repetitions=1, execution=execution)
    )
    error = results.failures[0].output.error
    assert error is not None
    assert error.type == "PermissionError"
    for secret in ("abc.def-123", "hunter2", "sk-live1234567890"):
        assert secret not in error.message
    assert "[REDACTED]" in error.message


def test_credential_redaction_patterns() -> None:
    assert redact_credentials('{"api_key": "abc123"}') == '{"api_key": "[REDACTED]"}'
    assert redact_credentials("password=pw&user=x") == "password=[REDACTED]&user=x"
    assert redact_credentials("plain message") == "plain message"


async def test_redactor_sanitizes_outputs_before_persistence() -> None:
    store = MemoryStore()

    def redact(output: TargetOutput) -> TargetOutput:
        return output.model_copy(update={"text": (output.text or "").replace("stable", "[x]")})

    results = await Runner(store=store, redact=redact).run(build(threshold_target(), repetitions=1))
    stored = store.get(Observation, [observation.id for observation in results.observations])
    assert all("stable" not in (observation.output.text or "") for observation in stored.values())
    assert stored == {observation.id: observation for observation in results.observations}


async def test_progress_reports_every_completion() -> None:
    events: list[Progress] = []
    results = await Runner(on_progress=events.append).run(build(threshold_target(), repetitions=2))
    assert events[0] == Progress(total=len(results.observations), completed=0, reused=0, failed=0)
    assert events[-1].completed == len(results.observations)
    assert len(events) == len(results.observations) + 1


async def test_measure_failures_are_reported_with_context() -> None:
    class Broken:
        @property
        def identity(self) -> Identity:
            return Identity(name="broken")

        async def compare(
            self, pairs: Sequence[tuple[Response, Response]]
        ) -> Sequence[MeasureValue]:
            return []

    class Crashing(Broken):
        async def compare(
            self, pairs: Sequence[tuple[Response, Response]]
        ) -> Sequence[MeasureValue]:
            raise ZeroDivisionError("division by zero")

    with pytest.raises(MeasureError, match="'broken' returned 0 values"):
        await Runner().run(build(threshold_target(), measures=[Broken()]))
    with pytest.raises(MeasureError, match="'broken' failed: division by zero") as failed:
        await Runner().run(build(threshold_target(), measures=[Crashing()]))
    assert isinstance(failed.value.__cause__, ZeroDivisionError)


def test_experiments_validate_their_specification() -> None:
    with pytest.raises(ExperimentError, match="at least one target"):
        Experiment(task_space=level_space(), targets=[])
    with pytest.raises(ExperimentError, match="Repetitions"):
        build(threshold_target(), repetitions=0)
    with pytest.raises(ExperimentError, match="unique name"):
        Experiment(task_space=level_space(), targets=[threshold_target(), threshold_target()])
    with pytest.raises(ExperimentError, match="unique name"):
        build(threshold_target(), measures=[TokenJaccardDistance(), TokenJaccardDistance()])


def test_designs_select_coordinates_explicitly() -> None:
    sweep = Experiment(task_space=level_space(), targets=[threshold_target()], design=Sweep())
    grid = Experiment(task_space=level_space(), targets=[threshold_target()], design=Grid())
    assert len(sweep.record.coordinates) == 5
    assert len(grid.record.coordinates) == 8
    assert sweep.id != grid.id


def scheduled(seed: int, repetitions: int = 4) -> list[ObservationJob]:
    targets = [threshold_target("a"), noisy_threshold_target("b")]
    variants = list(level_space().variants(level_space().sweep()))
    jobs = [
        ObservationJob(
            id=f"{target.identity.name}-{variant.id}-{repetition}",
            variant=variant,
            target=target,
            repetition=repetition,
            seed=0,
        )
        for target in targets
        for variant in variants
        for repetition in range(repetitions)
    ]
    return schedule(jobs, seed)


def test_schedule_runs_every_job_once_in_randomized_repetition_blocks() -> None:
    order = scheduled(seed=0)
    block = len(order) // 4
    assert len({job.id for job in order}) == len(order) == 2 * 15 * 4
    assert [job.position for job in order] == list(range(len(order)))
    assert [job.repetition for job in order] == [r for r in range(4) for _ in range(block)]
    sequences = [
        [(job.target.identity.name, job.variant.id) for job in order[r * block : (r + 1) * block]]
        for r in range(4)
    ]
    assert len({tuple(sequence) for sequence in sequences}) == 4
    first_half = {name for name, _ in sequences[0][: block // 2]}
    assert first_half == {"a", "b"}


def test_schedule_is_deterministic_from_the_experiment_seed() -> None:
    assert [job.id for job in scheduled(seed=3)] == [job.id for job in scheduled(seed=3)]
    assert [job.id for job in scheduled(seed=3)] != [job.id for job in scheduled(seed=4)]


async def test_observations_record_schedule_and_timing() -> None:
    results = await Runner().run(build(threshold_target(), repetitions=2))
    positions = sorted(observation.schedule_position for observation in results.observations)
    assert positions == list(range(len(results.observations)))
    assert all(o.completed_at >= o.started_at for o in results.observations)
    by_position = sorted(results.observations, key=lambda o: o.schedule_position)
    half = len(by_position) // 2
    assert {o.repetition for o in by_position[:half]} == {0}
    assert [o.coordinate for o in by_position[:half]] != [
        o.coordinate for o in sorted(by_position[:half], key=lambda o: (o.case_id, o.variant_id))
    ]
    rows = results.table()
    assert {"schedule_position", "started_at", "completed_at", "exact_match"} <= set(rows[0])


async def test_resumed_runs_keep_identity_and_schedule_positions() -> None:
    store = MemoryStore()
    first = await Runner(store=store).run(build(CountingTarget(), repetitions=2))
    target = CountingTarget()
    again = await Runner(store=store).run(build(target, repetitions=2))
    assert target.calls == 0
    assert [(o.id, o.schedule_position) for o in again.observations] == [
        (o.id, o.schedule_position) for o in first.observations
    ]
