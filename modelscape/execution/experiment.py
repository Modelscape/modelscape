from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from pydantic import Field

from modelscape.core.errors import ExperimentError
from modelscape.core.experiments import ExperimentRecord, Grid, Sweep
from modelscape.core.identity import Identity
from modelscape.core.serialization import FrozenModel
from modelscape.measures.protocols import DifferenceMeasure, PointMetric
from modelscape.space import TaskSpace
from modelscape.targets.protocols import Target


class RetryPolicy(FrozenModel):
    """Exponential backoff for target invocations that raise or time out."""

    max_attempts: int = Field(default=3, ge=1)
    initial_delay_seconds: float = Field(default=0.5, ge=0)
    backoff: float = Field(default=2.0, ge=1)
    max_delay_seconds: float = Field(default=30.0, ge=0)

    def delay(self, attempt: int) -> float:
        return min(
            self.max_delay_seconds, self.initial_delay_seconds * self.backoff ** (attempt - 1)
        )


class ExecutionConfig(FrozenModel):
    """How observations are executed. Does not affect observation identity."""

    concurrency: int = Field(default=8, ge=1)
    timeout_seconds: float | None = Field(default=60.0, gt=0)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)


@dataclass(frozen=True, kw_only=True, eq=False)
class Experiment:
    """A task space evaluated against targets with repetitions and explicit measures.

    ``design`` selects which coordinates are evaluated: a one-axis-at-a-time ``Sweep`` around
    the baseline by default, or a ``Grid`` when interactions between axes matter. ``seed`` is
    part of every observation identity, fixes the randomized execution schedule, and derives
    the seed hint passed to targets.
    """

    task_space: TaskSpace[Any]
    targets: Sequence[Target]
    repetitions: int = 1
    point_metrics: Sequence[PointMetric] = ()
    difference_measures: Sequence[DifferenceMeasure] = ()
    design: Sweep | Grid = field(default_factory=Sweep)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    seed: int = 0
    scenario: Identity | None = None

    def __post_init__(self) -> None:
        if not self.targets:
            raise ExperimentError("An experiment needs at least one target.")
        if self.repetitions < 1:
            raise ExperimentError(f"Repetitions must be at least 1, got {self.repetitions}.")
        if self.seed < 0:
            raise ExperimentError(f"Seed must be non-negative, got {self.seed}.")
        _require_unique("target", [target.identity for target in self.targets])
        _require_unique("point metric", [metric.identity for metric in self.point_metrics])
        _require_unique(
            "difference measure", [measure.identity for measure in self.difference_measures]
        )

    @cached_property
    def record(self) -> ExperimentRecord:
        return ExperimentRecord.create(
            scenario=self.scenario,
            space=self.task_space.coordinates,
            task_schema=self.task_space.describe(),
            realizer=self.task_space.realizer.identity,
            cases={case: task.fingerprint for case, task in self.task_space.cases.items()},
            targets=[target.identity for target in self.targets],
            repetitions=self.repetitions,
            point_metrics=[metric.identity for metric in self.point_metrics],
            difference_measures=[measure.identity for measure in self.difference_measures],
            design=self.design,
            seed=self.seed,
        )

    @property
    def id(self) -> str:
        return self.record.id


def _require_unique(kind: str, identities: Sequence[Identity]) -> None:
    names = [identity.name for identity in identities]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ExperimentError(f"Each {kind} needs a unique name; duplicated: {duplicates!r}.")
