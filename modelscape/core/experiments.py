from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from modelscape.core.coordinates import Coordinate, CoordinateSystem
from modelscape.core.identity import Identity
from modelscape.core.serialization import FrozenModel, stable_id
from modelscape.core.tasks import TaskSchema


class Sweep(FrozenModel):
    """Evaluate the baseline and every one-axis-at-a-time variation around it."""

    kind: Literal["sweep"] = "sweep"
    axes: tuple[str, ...] | None = None

    def coordinates(self, space: CoordinateSystem) -> tuple[Coordinate, ...]:
        return space.sweep(self.axes)


class Grid(FrozenModel):
    """Evaluate the full Cartesian product of the selected axes, others held at baseline."""

    kind: Literal["grid"] = "grid"
    axes: tuple[str, ...] | None = None

    def coordinates(self, space: CoordinateSystem) -> tuple[Coordinate, ...]:
        return tuple(space.grid(self.axes))


Design: TypeAlias = Annotated[Sweep | Grid, Field(discriminator="kind")]


class ExperimentRecord(FrozenModel):
    """A serializable description of an experiment, identified by a hash of its content."""

    id: str
    scenario: Identity | None = None
    space: CoordinateSystem
    task_schema: TaskSchema
    realizer: Identity
    case_ids: tuple[str, ...]
    case_fingerprints: tuple[str, ...]
    targets: tuple[Identity, ...]
    repetitions: int = Field(ge=1)
    point_metrics: tuple[Identity, ...]
    difference_measures: tuple[Identity, ...]
    design: Design
    seed: int

    @classmethod
    def create(
        cls,
        *,
        scenario: Identity | None = None,
        space: CoordinateSystem,
        task_schema: TaskSchema,
        realizer: Identity,
        cases: Mapping[str, str],
        targets: Sequence[Identity],
        repetitions: int,
        point_metrics: Sequence[Identity],
        difference_measures: Sequence[Identity],
        design: Sweep | Grid,
        seed: int,
    ) -> ExperimentRecord:
        content = {
            "scenario": scenario,
            "space": space,
            "task_schema": task_schema,
            "realizer": realizer,
            "case_ids": tuple(cases),
            "case_fingerprints": tuple(cases.values()),
            "targets": tuple(targets),
            "repetitions": repetitions,
            "point_metrics": tuple(point_metrics),
            "difference_measures": tuple(difference_measures),
            "design": design,
            "seed": seed,
        }
        draft = cls.model_validate({"id": "", **content})
        return draft.model_copy(
            update={"id": stable_id(draft.model_dump(mode="json", exclude={"id"}))}
        )

    @property
    def coordinates(self) -> tuple[Coordinate, ...]:
        return self.design.coordinates(self.space)


class RunManifest(FrozenModel):
    """The records that make up one completed run of an experiment."""

    id: str
    variant_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    point_measurement_ids: tuple[str, ...]
    difference_measurement_ids: tuple[str, ...]
    completed_at: datetime
