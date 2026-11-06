from __future__ import annotations

import itertools
from typing import Literal, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue, model_validator

from modelscape import Node, Prompt, Task, attribute, perturbation, realizer
from modelscape.core import ControlViolationError, PerturbationError, SchemaError, canonical_json
from modelscape.grammar import Attribute, JsonRealizer, perturb, structural_diff
from modelscape.grammar.diff import pointer

Reliability = Literal["low", "medium", "high"]


class Evidence(Node):
    id: str
    reliability: Reliability
    supports: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()


class Assessment(Task):
    hypotheses: tuple[str, ...]
    evidence: tuple[Evidence, ...]

    @model_validator(mode="after")
    def _references_resolve(self) -> Assessment:
        for item in self.evidence:
            unknown = set(item.supports + item.contradicts) - set(self.hypotheses)
            if unknown:
                raise ValueError(f"{item.id} refers to unknown hypotheses {sorted(unknown)}")
        return self

    @attribute
    def evidence_count(self) -> int:
        """Number of evidence items."""
        return len(self.evidence)

    @attribute
    def conflict(self) -> int:
        """Hypotheses that are both supported and contradicted."""
        supported = {name for item in self.evidence for name in item.supports}
        contradicted = {name for item in self.evidence for name in item.contradicts}
        return len(supported & contradicted)

    @attribute
    def reliable(self) -> int:
        return sum(item.reliability == "high" for item in self.evidence)

    def reference(self) -> str:
        return "H1"


SEED = Assessment(
    hypotheses=("H1", "H2"),
    evidence=(
        Evidence(id="E1", reliability="high", supports=("H1",)),
        Evidence(id="E2", reliability="low", supports=("H2",)),
    ),
)
POOL = tuple(Evidence(id=f"X{index}", reliability="medium", supports=("H1",)) for index in range(5))


@perturbation
def set_evidence_count(task: Assessment, count: int) -> Assessment:
    return task.replace(evidence=(*task.evidence, *POOL)[:count])


@perturbation
def set_conflict(task: Assessment, conflict: int) -> Assessment:
    contradiction = Evidence(id="C", reliability="high", contradicts=("H1",))
    return task.replace(evidence=(*task.evidence[:-1], contradiction))


@perturbation(free=["evidence_count"], version="2")
def add_conflict(task: Assessment, conflict: int) -> Assessment:
    contradictions = tuple(
        Evidence(id=f"C{index}", reliability="medium", contradicts=(name,))
        for index, name in enumerate(task.hypotheses[:conflict])
    )
    return task.replace(evidence=(*task.evidence, *contradictions))


def test_a_task_class_describes_its_language() -> None:
    schema = Assessment.describe()
    assert schema.name == "Assessment"
    assert [item.name for item in schema.attributes] == ["evidence_count", "conflict", "reliable"]
    assert schema.attributes[0].type == "int"
    assert schema.attributes[0].description == "Number of evidence items."
    assert schema.attributes[2].description is None
    assert set(cast(dict[str, object], schema.structure["properties"])) == {
        "hypotheses",
        "evidence",
    }
    assert schema.fingerprint == Assessment.describe().fingerprint


def test_attributes_are_computed_and_addressable() -> None:
    assert SEED.attributes() == {"evidence_count": 2, "conflict": 0, "reliable": 1}
    assert SEED.evidence_count == 2
    assert isinstance(Assessment.evidence_count, Attribute)
    assert Assessment.conflict.name == "conflict"
    assert SEED.reference() == "H1"


def test_tasks_are_immutable_well_formed_sentences() -> None:
    with pytest.raises(SchemaError, match="unknown hypotheses"):
        SEED.replace(evidence=(Evidence(id="E9", reliability="low", supports=("H7",)),))
    with pytest.raises(SchemaError, match="Not a valid Assessment"):
        SEED.replace(colour="red")
    with pytest.raises(ValueError, match="frozen"):
        SEED.__setattr__("hypotheses", ("H3",))
    assert SEED.replace(hypotheses=("H1", "H2")) == SEED


def test_attributes_must_be_finite_scalars() -> None:
    class Broken(Task):
        values: tuple[float, ...]

        @attribute
        def listed(self) -> int:
            return cast(int, list(self.values))

        @attribute
        def ratio(self) -> float:
            return float("inf")

    with pytest.raises(SchemaError, match="must be a bool, int, float, or str"):
        Broken.listed.of(Broken(values=(1.0,)))
    with pytest.raises(SchemaError, match="not finite"):
        Broken.ratio.of(Broken(values=(1.0,)))


def test_a_checked_step_reaches_its_value_and_is_recorded() -> None:
    result, step = perturb(set_evidence_count, SEED, case_id="seed", axis="evidence_count", value=4)
    assert result.evidence_count == 4
    assert (step.source, step.target, step.also_changed) == (2, 4, ())
    assert step.changed_paths == ("/evidence/2", "/evidence/3")
    assert step.parent_hash == SEED.fingerprint
    assert step.content_hash == result.fingerprint


def test_changing_a_controlled_attribute_is_rejected() -> None:
    with pytest.raises(ControlViolationError, match="evidence_count 2 -> 3") as caught:
        perturb(
            perturbation(name="unfree")(add_conflict.function),
            SEED,
            case_id="seed",
            axis="conflict",
            value=1,
        )
    assert caught.value.changes == {"evidence_count": (2, 3)}


def test_free_attributes_may_change_along_and_are_recorded() -> None:
    result, step = perturb(add_conflict, SEED, case_id="seed", axis="conflict", value=1)
    assert result.attributes() == {"evidence_count": 3, "conflict": 1, "reliable": 1}
    assert step.also_changed == ("evidence_count",)
    assert step.perturbation.parameters == {"free": ["evidence_count"]}
    assert step.perturbation.version == "2"


def test_a_step_that_misses_its_value_is_rejected() -> None:
    with pytest.raises(PerturbationError, match=r"asked for evidence_count=9 .* produced .*=7"):
        perturb(set_evidence_count, SEED, case_id="seed", axis="evidence_count", value=9)


def test_steps_that_also_change_other_controls_are_rejected() -> None:
    with pytest.raises(ControlViolationError, match="reliable 1 -> 2"):
        perturb(set_conflict, SEED, case_id="seed", axis="conflict", value=1)


def test_perturbations_must_be_deterministic_typed_and_well_behaved() -> None:
    counter = itertools.count()

    @perturbation
    def drifting(task: Assessment, count: int) -> Assessment:
        return task.replace(hypotheses=(*task.hypotheses, f"H{next(counter) + 3}"))

    @perturbation
    def failing(task: Assessment, count: int) -> Assessment:
        raise RuntimeError("no evidence left")

    @perturbation
    def retyped(task: Task, count: int) -> Task:
        return Task()

    with pytest.raises(PerturbationError, match="not deterministic"):
        perturb(drifting, SEED, case_id="seed", axis="evidence_count", value=2)
    with pytest.raises(PerturbationError, match=r"failed on case 'seed' .* no evidence left"):
        perturb(failing, SEED, case_id="seed", axis="evidence_count", value=3)
    with pytest.raises(PerturbationError, match="returned Task, expected Assessment"):
        perturb(retyped, SEED, case_id="seed", axis="evidence_count", value=3)


def test_rewrites_bypassing_validation_are_revalidated() -> None:
    @perturbation
    def sneaky(task: Assessment, count: int) -> Assessment:
        extra = Evidence(id="E9", reliability="low", supports=("H9",))
        return task.model_copy(update={"evidence": (*task.evidence, extra)})

    with pytest.raises(SchemaError, match="unknown hypotheses"):
        perturb(sneaky, SEED, case_id="seed", axis="evidence_count", value=3)


def test_realizers_produce_exact_prompts_with_identities() -> None:
    @realizer(system="Assess.", version="3")
    def brief(task: Assessment) -> str:
        return f"{task.evidence_count} items"

    @realizer
    def chat(task: Assessment) -> Prompt:
        return Prompt.of("Which hypothesis?", system="Be careful.")

    assert brief.realize(SEED) == Prompt.of("2 items", system="Assess.")
    assert brief.identity.version == "3"
    assert brief.identity.parameters == {"system": "Assess."}
    assert chat.realize(SEED).system == "Be careful."
    assert chat.identity.name == "chat"
    default = JsonRealizer().realize(SEED)
    assert '"hypotheses"' in default.last
    assert default.system is None


keys = st.text(min_size=1, max_size=6)
json_values: st.SearchStrategy[JsonValue] = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=5),
    lambda children: st.lists(children, max_size=3) | st.dictionaries(keys, children, max_size=3),
    max_leaves=12,
)


@given(json_values, json_values)
def test_differences_are_empty_exactly_when_documents_are_equal(
    left: JsonValue, right: JsonValue
) -> None:
    assert (structural_diff(left, right) == ()) == (canonical_json(left) == canonical_json(right))


def test_structural_diff_reports_deepest_changed_paths() -> None:
    before: JsonValue = {"a": {"b": 1, "c": [1, 2]}, "d": "x"}
    after: JsonValue = {"a": {"b": 2, "c": [1, 2, 3]}, "e": "x"}
    assert structural_diff(before, after) == ("/a/b", "/a/c/2", "/d", "/e")
    assert structural_diff({"a": 1}, {"a": True}) == ("/a",)
    assert pointer(["a/b", "~", 0]) == "/a~1b/~0/0"
