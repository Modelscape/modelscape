"""Task spaces: seed tasks, the attribute axes that vary them, and the variants they generate."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, Generic, TypeVar

from pydantic import ValidationError

from modelscape.core.coordinates import (
    AxisSpec,
    Coordinate,
    CoordinateSystem,
    NeighborPair,
    Scale,
    same_value,
)
from modelscape.core.errors import ModelscapeError, PerturbationError, TaskSpaceError
from modelscape.core.observations import Prompt
from modelscape.core.serialization import AxisValue
from modelscape.core.tasks import PerturbationStep, TaskSchema, Variant
from modelscape.grammar import (
    Attribute,
    JsonRealizer,
    Perturbation,
    Realizer,
    Task,
    attributes_of,
    perturb,
)

TaskT = TypeVar("TaskT", bound=Task)
ValueT = TypeVar("ValueT", bound=AxisValue)


class Axis(Generic[TaskT, ValueT]):
    """One attribute of a task language, varied over discrete values by one perturbation.

    ``scale`` is ``nominal``, ``ordinal``, or ``numeric``; see ``AxisSpec``. The baseline
    defaults to the first value.
    """

    __slots__ = ("_perturbation", "_spec")

    def __init__(
        self,
        attribute: Attribute[TaskT, ValueT] | str,
        values: Iterable[ValueT],
        via: Perturbation[TaskT, ValueT],
        *,
        scale: Scale,
        baseline: ValueT | None = None,
    ) -> None:
        declared: tuple[AxisValue, ...] = tuple(values)
        if not declared:
            raise TaskSpaceError("An axis needs at least one value.")
        self._perturbation = via
        try:
            self._spec = AxisSpec(
                name=attribute if isinstance(attribute, str) else attribute.name,
                values=declared,
                baseline=declared[0] if baseline is None else baseline,
                scale=scale,
                perturbation=via.identity,
            )
        except ValidationError as error:
            problems = (item["msg"].removeprefix("Value error, ") for item in error.errors())
            raise TaskSpaceError("; ".join(problems)) from error

    def __repr__(self) -> str:
        return (
            f"Axis({self.name!r}, values={self.values!r}, scale={self.scale!r}, "
            f"baseline={self.baseline!r}, via={self._spec.perturbation.name!r})"
        )

    @property
    def spec(self) -> AxisSpec:
        return self._spec

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def values(self) -> tuple[AxisValue, ...]:
        return self._spec.values

    @property
    def baseline(self) -> AxisValue:
        return self._spec.baseline

    @property
    def scale(self) -> Scale:
        return self._spec.scale

    @property
    def perturbation(self) -> Perturbation[TaskT, ValueT]:
        return self._perturbation


class TaskSpace(Generic[TaskT]):
    """Seed tasks of one task language, the axes that vary them, and how they are realized.

    The task at a coordinate is made from a seed by applying, in axis order, the perturbation
    of every axis whose attribute differs from the coordinate. Each step is checked, and the
    final task must have exactly the coordinate's attribute values.
    """

    __slots__ = ("_axes", "_cases", "_coordinates", "_realizer", "_schema")

    def __init__(
        self,
        cases: Mapping[str, TaskT],
        axes: Sequence[Axis[TaskT, Any]],
        realizer: Realizer[TaskT] | None = None,
    ) -> None:
        if not cases:
            raise TaskSpaceError("A task space needs at least one seed task.")
        schemas = {type(task) for task in cases.values()}
        if len(schemas) != 1:
            names = sorted(schema.__name__ for schema in schemas)
            raise TaskSpaceError(f"All seed tasks must share one task language, got {names}.")
        if not axes:
            raise TaskSpaceError("A task space needs at least one axis.")
        self._schema: type[TaskT] = schemas.pop()
        self._cases = dict(cases)
        self._axes = tuple(axes)
        self._realizer: Realizer[TaskT] = realizer or JsonRealizer()
        self._coordinates = CoordinateSystem(axes=tuple(axis.spec for axis in axes))
        self._check_attributes()

    def __repr__(self) -> str:
        return (
            f"TaskSpace({self._schema.__name__}, cases={len(self._cases)}, "
            f"axes={list(self._coordinates.axis_names)!r})"
        )

    @property
    def schema(self) -> type[TaskT]:
        return self._schema

    @property
    def cases(self) -> Mapping[str, TaskT]:
        return self._cases

    @property
    def axes(self) -> tuple[Axis[TaskT, Any], ...]:
        return self._axes

    @property
    def realizer(self) -> Realizer[TaskT]:
        return self._realizer

    @property
    def coordinates(self) -> CoordinateSystem:
        return self._coordinates

    @property
    def baseline(self) -> Coordinate:
        return self._coordinates.baseline

    def describe(self) -> TaskSchema:
        return self._schema.describe()

    def coordinate(self, **values: AxisValue) -> Coordinate:
        return self._coordinates.coordinate(values)

    def sweep(self, *axes: str) -> tuple[Coordinate, ...]:
        return self._coordinates.sweep(axes or None)

    def grid(self, *axes: str) -> Iterator[Coordinate]:
        return self._coordinates.grid(axes or None)

    def neighbors(self, coordinates: Iterable[Mapping[str, AxisValue]]) -> tuple[NeighborPair, ...]:
        return self._coordinates.neighbors(coordinates)

    def task(self, case: str, coordinate: Mapping[str, AxisValue] | None = None) -> TaskT:
        """The task of one seed at one coordinate; axes you leave out stay at their baseline."""
        return self._derive(case, self._coordinates.coordinate(coordinate))[0]

    def variant(self, case: str, coordinate: Mapping[str, AxisValue] | None = None) -> Variant:
        """The task at a coordinate, with its prompt and the record of every step."""
        location = self._coordinates.coordinate(coordinate)
        task, steps = self._derive(case, location)
        return Variant.create(
            case_id=case,
            coordinate=location,
            task=task.content(),
            attributes=task.attributes(),
            reference=task.reference(),
            prompt=self._realize(task, case),
            steps=steps,
        )

    def variants(self, coordinates: Iterable[Mapping[str, AxisValue]]) -> Iterator[Variant]:
        locations = [self._coordinates.coordinate(values) for values in coordinates]
        for case in self._cases:
            for location in locations:
                yield self.variant(case, location)

    def _derive(self, case: str, location: Coordinate) -> tuple[TaskT, list[PerturbationStep]]:
        if case not in self._cases:
            raise TaskSpaceError(f"Unknown seed task '{case}'.")
        task = self._cases[case]
        steps: list[PerturbationStep] = []
        for axis in self._axes:
            value = location[axis.name]
            if not same_value(task.attributes()[axis.name], value):
                task, step = perturb(
                    axis.perturbation, task, case_id=case, axis=axis.name, value=value
                )
                steps.append(step)
        reached = task.attributes()
        missed = [name for name, value in location.items() if not same_value(reached[name], value)]
        if missed:
            found = ", ".join(f"{name}={reached[name]!r}" for name in missed)
            raise PerturbationError(
                f"Case '{case}' should be at {location}, but after all perturbations it has "
                f"{found}."
            )
        return task, steps

    def _realize(self, task: TaskT, case: str) -> Prompt:
        try:
            return self._realizer.realize(task)
        except ModelscapeError:
            raise
        except Exception as error:
            raise TaskSpaceError(
                f"Realizer '{self._realizer.identity.name}' failed on case '{case}': {error}"
            ) from error

    def _check_attributes(self) -> None:
        known = set(attributes_of(self._schema))
        for axis in self._axes:
            if axis.name not in known:
                raise TaskSpaceError(
                    f"Axis '{axis.name}' is not an attribute of {self._schema.__name__}; "
                    f"its attributes are {sorted(known)}."
                )
            unknown = sorted(axis.perturbation.free - known)
            if unknown:
                raise TaskSpaceError(
                    f"Perturbation '{axis.spec.perturbation.name}' lists unknown free attributes "
                    f"{unknown}."
                )
