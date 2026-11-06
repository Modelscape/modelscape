from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Literal, TypeAlias, TypeGuard

from pydantic import Field, GetCoreSchemaHandler, model_validator
from pydantic_core import core_schema

from modelscape.core.errors import TaskSpaceError
from modelscape.core.identity import Identity
from modelscape.core.serialization import AxisValue, FrozenModel, canonical_json

Scale: TypeAlias = Literal["nominal", "ordinal", "numeric"]


def same_value(left: AxisValue, right: AxisValue) -> bool:
    return type(left) is type(right) and left == right


def is_number(value: AxisValue) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


class Coordinate(Mapping[str, AxisValue]):
    """Immutable location in a task space, mapping every axis name to one declared value."""

    __slots__ = ("_key", "_values")

    def __init__(self, values: Mapping[str, AxisValue] | None = None) -> None:
        self._values: dict[str, AxisValue] = dict(values or {})
        self._key = canonical_json(self._values)

    def __getitem__(self, axis: str) -> AxisValue:
        return self._values[axis]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __hash__(self) -> int:
        return hash(self._key)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Coordinate):
            return NotImplemented
        return self._key == other._key

    def __repr__(self) -> str:
        return f"Coordinate({self._values!r})"

    def __str__(self) -> str:
        return ", ".join(f"{axis}={value!r}" for axis, value in self._values.items()) or "∅"

    @property
    def key(self) -> str:
        return self._key

    def replace(self, axis: str, value: AxisValue) -> Coordinate:
        if axis not in self._values:
            raise TaskSpaceError(f"Coordinate {self} has no axis '{axis}'.")
        return Coordinate({**self._values, axis: value})

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type[object], handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            handler.generate_schema(dict[str, AxisValue]),
            serialization=core_schema.plain_serializer_function_ser_schema(dict),
        )


class AxisSpec(FrozenModel):
    """Serializable description of one discrete task-space axis.

    The scale says how its values relate. ``nominal`` values are only compared with the
    baseline. ``ordinal`` values are in the declared order, so adjacent values are neighbors.
    ``numeric`` values are numbers in ascending order, so a step also has a size.
    """

    name: str = Field(min_length=1)
    values: tuple[AxisValue, ...] = Field(min_length=1)
    baseline: AxisValue
    scale: Scale
    perturbation: Identity

    @model_validator(mode="after")
    def _validate_values(self) -> AxisSpec:
        keys = [canonical_json(value) for value in self.values]
        if len(set(keys)) != len(keys):
            raise ValueError(f"Axis '{self.name}' declares duplicate values {list(self.values)!r}.")
        if not any(same_value(value, self.baseline) for value in self.values):
            raise ValueError(
                f"Baseline {self.baseline!r} of axis '{self.name}' is not one of its values "
                f"{list(self.values)!r}."
            )
        if self.scale == "numeric":
            if not all(is_number(value) for value in self.values):
                raise ValueError(
                    f"Numeric axis '{self.name}' needs numbers, got {list(self.values)!r}."
                )
            if list(self.values) != sorted(self.values):
                raise ValueError(
                    f"Numeric axis '{self.name}' needs its values in ascending order, got "
                    f"{list(self.values)!r}."
                )
        return self

    @property
    def ordered(self) -> bool:
        return self.scale != "nominal"

    def index(self, value: AxisValue) -> int:
        for position, candidate in enumerate(self.values):
            if same_value(candidate, value):
                return position
        raise TaskSpaceError(
            f"Value {value!r} is not declared on axis '{self.name}'; "
            f"declared values are {list(self.values)!r}."
        )


class NeighborPair(FrozenModel):
    """Two coordinates that differ by one adjacent step on exactly one ordinal or numeric axis."""

    axis: str
    start: Coordinate
    end: Coordinate


class CoordinateSystem(FrozenModel):
    """The geometry of a task space: its axes, baseline, and neighbor structure."""

    axes: tuple[AxisSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_axes(self) -> CoordinateSystem:
        names = self.axis_names
        if len(set(names)) != len(names):
            raise ValueError(f"Axis names must be unique, got {list(names)!r}.")
        return self

    @property
    def axis_names(self) -> tuple[str, ...]:
        return tuple(axis.name for axis in self.axes)

    @property
    def baseline(self) -> Coordinate:
        return Coordinate({axis.name: axis.baseline for axis in self.axes})

    def axis(self, name: str) -> AxisSpec:
        for axis in self.axes:
            if axis.name == name:
                return axis
        raise TaskSpaceError(f"Unknown axis '{name}'; known axes are {list(self.axis_names)!r}.")

    def coordinate(self, values: Mapping[str, AxisValue] | None = None) -> Coordinate:
        """Resolve a complete coordinate, filling unspecified axes with their baseline values."""
        given = dict(values or {})
        unknown = [name for name in given if name not in self.axis_names]
        if unknown:
            raise TaskSpaceError(
                f"Unknown axes {unknown!r}; known axes are {list(self.axis_names)!r}."
            )
        resolved: dict[str, AxisValue] = {}
        for axis in self.axes:
            value = given.get(axis.name, axis.baseline)
            axis.index(value)
            resolved[axis.name] = value
        return Coordinate(resolved)

    def line(
        self, axis: str, fixed: Mapping[str, AxisValue] | None = None
    ) -> tuple[Coordinate, ...]:
        """All coordinates along one axis, holding every other axis at a fixed value."""
        spec = self.axis(axis)
        if fixed is not None and axis in fixed:
            raise TaskSpaceError(f"Axis '{axis}' cannot be both varied and fixed.")
        anchor = self.coordinate(fixed)
        return tuple(anchor.replace(axis, value) for value in spec.values)

    def sweep(self, axes: Sequence[str] | None = None) -> tuple[Coordinate, ...]:
        """The baseline followed by one-axis-at-a-time variations around it."""
        baseline = self.baseline
        coordinates = [baseline]
        for name in self._select(axes):
            axis = self.axis(name)
            coordinates.extend(
                baseline.replace(name, value)
                for value in axis.values
                if not same_value(value, axis.baseline)
            )
        return tuple(coordinates)

    def grid(self, axes: Sequence[str] | None = None) -> Iterator[Coordinate]:
        """The Cartesian product of the selected axes, holding all others at baseline."""
        selected = self._select(axes)
        baseline = self.baseline
        for values in itertools.product(*(self.axis(name).values for name in selected)):
            coordinate = baseline
            for name, value in zip(selected, values, strict=True):
                coordinate = coordinate.replace(name, value)
            yield coordinate

    def neighbors(self, coordinates: Iterable[Mapping[str, AxisValue]]) -> tuple[NeighborPair, ...]:
        """Adjacent pairs among the given coordinates along every ordinal and numeric axis."""
        present = list(dict.fromkeys(self.coordinate(values) for values in coordinates))
        lookup = set(present)
        pairs: list[NeighborPair] = []
        for coordinate in present:
            for axis in self.axes:
                position = axis.index(coordinate[axis.name])
                if not axis.ordered or position + 1 >= len(axis.values):
                    continue
                neighbor = coordinate.replace(axis.name, axis.values[position + 1])
                if neighbor in lookup:
                    pairs.append(NeighborPair(axis=axis.name, start=coordinate, end=neighbor))
        return tuple(pairs)

    def _select(self, axes: Sequence[str] | None) -> tuple[str, ...]:
        if axes is None:
            return self.axis_names
        if isinstance(axes, str):
            raise TaskSpaceError("Axes must be given as a sequence of names, not a single string.")
        for name in axes:
            self.axis(name)
        if len(set(axes)) != len(axes):
            raise TaskSpaceError(f"Axes must be unique, got {list(axes)!r}.")
        return tuple(axes)
