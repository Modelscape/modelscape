from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from modelscape.core import AxisSpec, Coordinate, CoordinateSystem, Identity, TaskSpaceError

IDENTITY = Identity(name="test")


def differing(first: Coordinate, second: Coordinate) -> tuple[str, ...]:
    return tuple(axis for axis in first if first[axis] != second[axis])


@st.composite
def systems(draw: st.DrawFn) -> CoordinateSystem:
    count = draw(st.integers(min_value=1, max_value=3))
    axes: list[AxisSpec] = []
    for index in range(count):
        values = tuple(range(draw(st.integers(min_value=1, max_value=4))))
        axes.append(
            AxisSpec(
                name=f"axis{index}",
                values=values,
                baseline=draw(st.sampled_from(values)),
                scale=draw(st.sampled_from(["nominal", "ordinal", "numeric"])),
                perturbation=IDENTITY,
            )
        )
    return CoordinateSystem(axes=tuple(axes))


def test_coordinates_compare_by_value_and_type() -> None:
    assert Coordinate({"a": 1, "b": "x"}) == Coordinate({"b": "x", "a": 1})
    assert hash(Coordinate({"a": 1})) == hash(Coordinate({"a": 1}))
    assert Coordinate({"a": 1}) != Coordinate({"a": True})
    assert Coordinate({"a": 1}) != Coordinate({"a": 1.0})


def test_coordinate_round_trips_through_json() -> None:
    pair = CoordinateSystem(
        axes=(
            AxisSpec(name="a", values=(1, 2), baseline=1, scale="ordinal", perturbation=IDENTITY),
        )
    ).neighbors([{"a": 1}, {"a": 2}])[0]
    restored = type(pair).model_validate_json(pair.model_dump_json())
    assert restored == pair
    assert isinstance(restored.start, Coordinate)


def test_numeric_axes_hold_numbers_in_ascending_order() -> None:
    AxisSpec(name="a", values=(0, 2.5, 10), baseline=0, scale="numeric", perturbation=IDENTITY)
    AxisSpec(name="a", values=(2, 1), baseline=2, scale="ordinal", perturbation=IDENTITY)
    with pytest.raises(ValidationError, match="ascending order"):
        AxisSpec(name="a", values=(2, 1), baseline=2, scale="numeric", perturbation=IDENTITY)
    with pytest.raises(ValidationError, match="needs numbers"):
        AxisSpec(
            name="a", values=(False, True), baseline=False, scale="numeric", perturbation=IDENTITY
        )


def test_nominal_axes_have_no_neighbors() -> None:
    system = CoordinateSystem(
        axes=(
            AxisSpec(
                name="a", values=("x", "y"), baseline="x", scale="nominal", perturbation=IDENTITY
            ),
        )
    )
    assert system.neighbors(system.grid()) == ()


def test_axis_spec_rejects_duplicate_values_and_foreign_baseline() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        AxisSpec(name="a", values=(1, 1), baseline=1, scale="ordinal", perturbation=IDENTITY)
    with pytest.raises(ValidationError, match="not one of its values"):
        AxisSpec(name="a", values=(1, 2), baseline=3, scale="ordinal", perturbation=IDENTITY)


def test_coordinate_resolution_fills_baseline_and_rejects_unknown_input() -> None:
    system = CoordinateSystem(
        axes=(
            AxisSpec(name="a", values=(1, 2), baseline=1, scale="ordinal", perturbation=IDENTITY),
            AxisSpec(
                name="b", values=("x", "y"), baseline="y", scale="nominal", perturbation=IDENTITY
            ),
        )
    )
    assert system.coordinate({"a": 2}) == Coordinate({"a": 2, "b": "y"})
    with pytest.raises(TaskSpaceError, match="Unknown axes"):
        system.coordinate({"c": 1})
    with pytest.raises(TaskSpaceError, match="not declared"):
        system.coordinate({"a": 3})


@given(systems())
def test_baseline_is_stable_and_first_in_every_sweep(system: CoordinateSystem) -> None:
    sweep = system.sweep()
    assert sweep[0] == system.baseline == system.coordinate()
    assert len(set(sweep)) == len(sweep)
    for coordinate in sweep[1:]:
        assert len(differing(coordinate, system.baseline)) == 1


@given(systems())
def test_grid_is_the_full_cartesian_product(system: CoordinateSystem) -> None:
    grid = list(system.grid())
    expected = 1
    for axis in system.axes:
        expected *= len(axis.values)
    assert len(grid) == len(set(grid)) == expected
    assert system.baseline in grid


@given(systems())
def test_neighbors_differ_on_exactly_one_ordered_axis_by_one_step(system: CoordinateSystem) -> None:
    for pair in system.neighbors(system.grid()):
        assert differing(pair.start, pair.end) == (pair.axis,)
        axis = system.axis(pair.axis)
        assert axis.ordered
        assert axis.index(pair.end[pair.axis]) == axis.index(pair.start[pair.axis]) + 1


@given(systems())
def test_neighbors_cover_every_adjacent_pair_in_the_grid(system: CoordinateSystem) -> None:
    expected = 0
    for axis in system.axes:
        others = 1
        for other in system.axes:
            if other.name != axis.name:
                others *= len(other.values)
        expected += (len(axis.values) - 1) * others * axis.ordered
    assert len(system.neighbors(system.grid())) == expected


def test_neighbors_never_bridge_missing_coordinates() -> None:
    system = CoordinateSystem(
        axes=(
            AxisSpec(
                name="a", values=(0, 1, 2), baseline=0, scale="ordinal", perturbation=IDENTITY
            ),
        )
    )
    assert system.neighbors([{"a": 0}, {"a": 2}]) == ()


def test_line_holds_other_axes_fixed() -> None:
    system = CoordinateSystem(
        axes=(
            AxisSpec(
                name="a", values=(0, 1, 2), baseline=0, scale="ordinal", perturbation=IDENTITY
            ),
            AxisSpec(name="b", values=(0, 1), baseline=0, scale="ordinal", perturbation=IDENTITY),
        )
    )
    line = system.line("a", {"b": 1})
    assert [coordinate["a"] for coordinate in line] == [0, 1, 2]
    assert all(coordinate["b"] == 1 for coordinate in line)
    with pytest.raises(TaskSpaceError, match="both varied and fixed"):
        system.line("a", {"a": 1})
