from __future__ import annotations

from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from modelscape import Axis, Task, TaskSpace, attribute, perturbation, realizer
from modelscape.core import Coordinate, PerturbationError, TaskSpaceError
from modelscape.grammar import Realizer
from tests.helpers import Probe, level_space, probe_cases, set_level, set_notes, set_style

coordinates = st.fixed_dictionaries(
    {"level": st.sampled_from([0, 1, 2, 3]), "style": st.sampled_from(["plain", "formal"])}
)


@given(coordinates)
def test_variant_ids_are_deterministic(coordinate: dict[str, int | str]) -> None:
    first = level_space().variant("case-0", coordinate)
    second = level_space().variant("case-0", coordinate)
    assert first.id == second.id
    assert first == second


@given(coordinates, coordinates)
def test_variant_ids_differ_when_content_or_coordinate_differs(
    left: dict[str, int | str], right: dict[str, int | str]
) -> None:
    space = level_space()
    same = Coordinate(left) == Coordinate(right)
    assert (space.variant("case-0", left).id == space.variant("case-0", right).id) == same
    assert space.variant("case-0", left).id != space.variant("case-1", left).id


def test_baseline_variant_is_the_unchanged_seed() -> None:
    space = level_space()
    variant = space.variant("case-1")
    assert variant.steps == ()
    assert variant.task == space.cases["case-1"].content()
    assert variant.coordinate == space.baseline
    assert variant.attributes == {"level": 0, "style": "plain", "note_count": 0}
    assert variant.reference == "stable"


def test_variants_carry_verified_attributes_and_their_exact_prompt() -> None:
    variant = level_space().variant("case-0", {"level": 2, "style": "formal"})
    assert [step.axis for step in variant.steps] == ["level", "style"]
    assert variant.steps[0].content_hash == variant.steps[1].parent_hash
    assert variant.steps[-1].content_hash == variant.content_hash
    assert variant.changed_paths == ("/intensity", "/tone")
    assert variant.attributes["level"] == 2
    assert '"tone": "formal"' in variant.prompt.last


def test_seeds_away_from_the_baseline_are_moved_onto_it() -> None:
    space = level_space({"far": Probe(question="question 9", intensity=3)})
    variant = space.variant("far")
    assert variant.attributes["level"] == 0
    assert [(step.source, step.target) for step in variant.steps] == [(3, 0)]
    assert space.variant("far", {"level": 3}).steps == ()


def test_typed_tasks_are_available_at_every_coordinate() -> None:
    task = level_space().task("case-2", {"level": 3})
    assert isinstance(task, Probe)
    assert task.level == 3


def test_wording_is_part_of_variant_identity() -> None:
    @realizer(version="1")
    def terse(task: Probe) -> str:
        return task.question

    @realizer(version="2")
    def polite(task: Probe) -> str:
        return f"Please answer: {task.question}"

    def space(wording: Realizer[Probe]) -> TaskSpace[Probe]:
        return TaskSpace(
            cases=probe_cases(1),
            axes=[Axis(Probe.level, (0, 1), via=set_level, scale="numeric")],
            realizer=wording,
        )

    first, second = space(terse).variant("case-0"), space(polite).variant("case-0")
    assert first.content_hash == second.content_hash
    assert first.id != second.id
    assert second.prompt.last == "Please answer: question 0"


def test_variants_are_generated_lazily_case_by_case() -> None:
    space = level_space()
    generated = space.variants(space.sweep())
    first = next(generated)
    assert first.case_id == "case-0"
    assert first.steps == ()
    assert len(list(generated)) == len(space.cases) * len(space.sweep()) - 1


def test_axes_must_land_exactly_on_their_coordinate() -> None:
    @perturbation(free=["level"])
    def notes_and_level(task: Probe, count: int) -> Probe:
        return set_notes.apply(task, count).replace(intensity=count)

    space = TaskSpace(
        cases=probe_cases(1),
        axes=[
            Axis(Probe.level, (0, 1, 2), via=set_level, scale="numeric"),
            Axis(Probe.note_count, (0, 1, 2), via=notes_and_level, scale="numeric"),
        ],
    )
    assert space.variant("case-0", {"note_count": 0}).attributes["level"] == 0
    with pytest.raises(PerturbationError, match=r"should be at .* it has level=2"):
        space.variant("case-0", {"note_count": 2})


def test_task_space_validation_is_precise() -> None:
    class Other(Task):
        name: str

        @attribute
        def level(self) -> int:
            return 0

    axes = [Axis(Probe.level, (0, 1), via=set_level, scale="numeric")]
    with pytest.raises(TaskSpaceError, match="at least one seed"):
        TaskSpace(cases={}, axes=axes)
    mixed = cast(dict[str, Probe], {"a": Probe(question="q"), "b": Other(name="o")})
    with pytest.raises(TaskSpaceError, match="one task language"):
        TaskSpace(cases=mixed, axes=axes)
    with pytest.raises(TaskSpaceError, match="at least one axis"):
        TaskSpace(cases=probe_cases(1), axes=[])
    with pytest.raises(TaskSpaceError, match="'loudness' is not an attribute of Probe"):
        TaskSpace(
            cases=probe_cases(1), axes=[Axis("loudness", (0, 1), via=set_level, scale="numeric")]
        )
    with pytest.raises(TaskSpaceError, match="lists unknown free attributes"):
        TaskSpace(
            cases=probe_cases(1),
            axes=[
                Axis(
                    Probe.level,
                    (0, 1),
                    via=perturbation(free=["mood"])(set_level.function),
                    scale="numeric",
                )
            ],
        )
    with pytest.raises(TaskSpaceError, match="Unknown seed task"):
        level_space().variant("missing")
    with pytest.raises(TaskSpaceError, match="at least one value"):
        Axis(Probe.level, (), via=set_level, scale="numeric")


def test_axis_exposes_a_serializable_spec() -> None:
    axis = Axis(Probe.style, ("plain", "formal"), via=set_style, scale="nominal")
    assert axis.name == "style"
    assert axis.baseline == "plain"
    assert axis.spec.perturbation.name == "set_style"
    assert axis.spec.model_validate_json(axis.spec.model_dump_json()) == axis.spec


def test_failing_realizers_name_the_case() -> None:
    @realizer
    def broken(task: Probe) -> str:
        raise KeyError(task.question)

    space = TaskSpace(
        cases=probe_cases(1),
        axes=[Axis(Probe.level, (0, 1), via=set_level, scale="numeric")],
        realizer=broken,
    )
    with pytest.raises(TaskSpaceError, match="Realizer 'broken' failed on case 'case-0'"):
        space.variant("case-0")


def test_sweeps_and_grids_can_be_limited_to_named_axes() -> None:
    space = level_space()
    assert [coordinate["style"] for coordinate in space.sweep("style")] == ["plain", "formal"]
    assert len(list(space.grid("level"))) == 4
    with pytest.raises(TaskSpaceError, match="Unknown axis 'loudness'"):
        space.sweep("loudness")
    with pytest.raises(TaskSpaceError, match="Axes must be unique"):
        list(space.grid("level", "level"))
    with pytest.raises(TaskSpaceError, match="not a single string"):
        space.coordinates.sweep("level")
