from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from modelscape.analysis.comparisons import measured_pairs
from modelscape.analysis.results import Results
from modelscape.core.errors import MeasureError, ModelscapeError
from modelscape.core.experiments import RunManifest
from modelscape.core.identity import Identity
from modelscape.core.measurements import DifferenceMeasurement, MeasureValue, PointMeasurement
from modelscape.core.observations import Observation, TargetOutput, observation_id, request_seed
from modelscape.core.tasks import Variant
from modelscape.execution.experiment import Experiment
from modelscape.execution.jobs import ObservationJob, execute, schedule
from modelscape.measures.protocols import Response
from modelscape.storage.memory import MemoryStore
from modelscape.storage.protocols import Store
from modelscape.targets.protocols import Target


@dataclass(frozen=True)
class Progress:
    total: int
    completed: int
    reused: int
    failed: int


ProgressCallback = Callable[[Progress], None]
Redactor = Callable[[TargetOutput], TargetOutput]


class Runner:
    """Runs experiments, saving each output as it arrives and reusing stored ones on reruns.

    Observations run in a fresh random order per repetition. ``redact`` cleans every output
    before it is stored.
    """

    __slots__ = ("_on_progress", "_redact", "_store")

    def __init__(
        self,
        *,
        store: Store | None = None,
        on_progress: ProgressCallback | None = None,
        redact: Redactor | None = None,
    ) -> None:
        self._store: Store = store if store is not None else MemoryStore()
        self._on_progress = on_progress
        self._redact = redact

    @property
    def store(self) -> Store:
        return self._store

    async def run(self, experiment: Experiment) -> Results:
        record = experiment.record
        space = experiment.task_space
        variants = list(space.variants(record.coordinates))
        self._store.put([record, *variants])
        observations = await self._observe(experiment, variants)
        by_id = {variant.id: variant for variant in variants}
        points = await self._score(experiment, by_id, observations)
        differences = await self._compare(experiment, by_id, observations)
        self._store.put(
            [
                RunManifest(
                    id=record.id,
                    variant_ids=tuple(variant.id for variant in variants),
                    observation_ids=tuple(observation.id for observation in observations),
                    point_measurement_ids=tuple(measurement.id for measurement in points),
                    difference_measurement_ids=tuple(measurement.id for measurement in differences),
                    completed_at=datetime.now(UTC),
                )
            ]
        )
        return Results(record, variants, observations, points, differences)

    async def _observe(
        self, experiment: Experiment, variants: Sequence[Variant]
    ) -> list[Observation]:
        jobs = [
            _job(variant, target, repetition, experiment.seed)
            for target in experiment.targets
            for variant in variants
            for repetition in range(experiment.repetitions)
        ]
        existing = self._store.get(Observation, [job.id for job in jobs])
        collected = {key: value for key, value in existing.items() if value.succeeded}
        pending = [job for job in schedule(jobs, experiment.seed) if job.id not in collected]
        progress = Progress(
            total=len(jobs), completed=len(collected), reused=len(collected), failed=0
        )
        self._report(progress)
        async for observation in execute(pending, experiment.execution):
            sanitized = self._sanitize(observation)
            self._store.put([sanitized])
            collected[sanitized.id] = sanitized
            progress = replace(
                progress,
                completed=progress.completed + 1,
                failed=progress.failed + (not sanitized.succeeded),
            )
            self._report(progress)
        return [collected[job.id] for job in jobs]

    async def _score(
        self,
        experiment: Experiment,
        variants: Mapping[str, Variant],
        observations: Sequence[Observation],
    ) -> list[PointMeasurement]:
        successful = [observation for observation in observations if observation.succeeded]
        records: list[PointMeasurement] = []
        for metric in experiment.point_metrics:
            identity = metric.identity
            keys = [PointMeasurement.key(identity, observation.id) for observation in successful]
            existing = self._store.get(PointMeasurement, keys)
            missing = [
                observation
                for observation, key in zip(successful, keys, strict=True)
                if key not in existing
            ]
            items = [_response(variants, observation) for observation in missing]
            values = await _measured(identity, len(items), metric.score(items)) if items else []
            created = [
                PointMeasurement.create(identity, observation.id, value)
                for observation, value in zip(missing, values, strict=True)
            ]
            self._store.put(created)
            fresh = {record.id: record for record in created}
            records.extend(existing.get(key) or fresh[key] for key in keys)
        return records

    async def _compare(
        self,
        experiment: Experiment,
        variants: Mapping[str, Variant],
        observations: Sequence[Observation],
    ) -> list[DifferenceMeasurement]:
        record = experiment.record
        pairs = measured_pairs(
            record.space,
            record.coordinates,
            observations,
            [target.name for target in record.targets],
        )
        records: list[DifferenceMeasurement] = []
        for measure in experiment.difference_measures:
            identity = measure.identity
            keys = [DifferenceMeasurement.key(identity, start.id, end.id) for start, end in pairs]
            existing = self._store.get(DifferenceMeasurement, keys)
            missing = [pair for pair, key in zip(pairs, keys, strict=True) if key not in existing]
            compared = [
                (_response(variants, start), _response(variants, end)) for start, end in missing
            ]
            values = (
                await _measured(identity, len(compared), measure.compare(compared))
                if compared
                else []
            )
            created = [
                DifferenceMeasurement.create(identity, start.id, end.id, value)
                for (start, end), value in zip(missing, values, strict=True)
            ]
            self._store.put(created)
            fresh = {item.id: item for item in created}
            records.extend(existing.get(key) or fresh[key] for key in keys)
        return records

    def _sanitize(self, observation: Observation) -> Observation:
        if self._redact is None:
            return observation
        return observation.model_copy(update={"output": self._redact(observation.output)})

    def _report(self, progress: Progress) -> None:
        if self._on_progress is not None:
            self._on_progress(progress)


def _job(variant: Variant, target: Target, repetition: int, seed: int) -> ObservationJob:
    identifier = observation_id(variant.id, target.identity.fingerprint, repetition, seed)
    return ObservationJob(
        id=identifier,
        variant=variant,
        target=target,
        repetition=repetition,
        seed=request_seed(identifier),
    )


def _response(variants: Mapping[str, Variant], observation: Observation) -> Response:
    return Response(variants[observation.variant_id], observation.output)


async def _measured(
    identity: Identity, expected: int, pending: Awaitable[Sequence[MeasureValue]]
) -> list[MeasureValue]:
    try:
        values = list(await pending)
    except ModelscapeError:
        raise
    except Exception as error:
        raise MeasureError(f"Measure '{identity.name}' failed: {error}") from error
    if len(values) != expected:
        raise MeasureError(
            f"Measure '{identity.name}' returned {len(values)} values for {expected} items."
        )
    return values
