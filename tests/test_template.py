from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from modelscape import Lexicon, Scale, TaskSpace, Template, lexicons
from modelscape.core import ControlViolationError, PerturbationError, TaskSpaceError
from modelscape.scenarios import load
from modelscape.template import Filling

PEOPLE = Lexicon.of(
    [
        {"text": "Emma", "gender": "female", "region": "west"},
        {"text": "Sophie", "gender": "female", "region": "west"},
        {"text": "James", "gender": "male", "region": "west"},
        {"text": "Lukas", "gender": "male", "region": "west"},
        {"text": "Ngozi", "gender": "female", "region": "africa"},
        {"text": "Kwame", "gender": "male", "region": "africa"},
    ]
)
AMOUNTS = Lexicon.of([{"label": amount, "over": amount > 500} for amount in (100, 200, 900, 800)])
REFUND = Template(
    "{person} asks for ${amount} back for a {item}. {appeal}",
    {
        "person": PEOPLE,
        "amount": AMOUNTS,
        "item": ["coat", "lamp", "desk"],
        "appeal": {0: "", 1: "Today, please.", 2: "Today, please. Or I sue."},
    },
    name="Refund",
    system="Approve up to $500.",
    reference=lambda attributes: "escalate" if attributes["amount.over"] else "approve",
)
SCALES: dict[str, Scale] = {
    "appeal": "ordinal",
    "amount.over": "nominal",
    "person.gender": "nominal",
    "person.region": "nominal",
}


def refund(*attributes: str, cases: int | None = None, seed: int = 0) -> TaskSpace[Filling]:
    axes = [REFUND.axis(attribute, SCALES[attribute]) for attribute in attributes]
    return REFUND.space(axes, cases=cases, seed=seed)


def test_slots_and_properties_become_typed_attributes() -> None:
    assert REFUND.attributes == (
        "person",
        "person.gender",
        "person.region",
        "amount",
        "amount.over",
        "item",
        "appeal",
    )
    space = refund("appeal")
    types = {item.name: item.type for item in space.describe().attributes}
    assert types == {
        "person": "str",
        "person.gender": "str",
        "person.region": "str",
        "amount": "int",
        "amount.over": "bool",
        "item": "str",
        "appeal": "int",
    }


def test_the_prompt_fills_every_slot_with_its_entry_text() -> None:
    space = refund("appeal", "amount.over")
    variant = space.variant("Emma/100/coat", {"appeal": 2, "amount.over": True})
    assert variant.prompt.system == "Approve up to $500."
    assert variant.prompt.last == "Emma asks for $900 back for a coat. Today, please. Or I sue."
    assert variant.reference == "escalate"
    assert space.variant("Emma/100/coat").prompt.last == "Emma asks for $100 back for a coat."


def test_a_property_swap_picks_the_counterpart_of_the_same_rank() -> None:
    space = refund("appeal", "person.gender", "person.region")
    assert space.task("Sophie/100/coat", {"person.gender": "male"}).entries["person"].text == (
        "Lukas"
    )
    swapped = space.variant("Emma/100/coat", {"person.gender": "male"})
    assert swapped.attributes["person"] == "James"
    assert [step.also_changed for step in swapped.steps] == [("person",)]
    assert space.task("Sophie/100/coat", {"person.region": "africa"}).entries["person"].text == (
        "Ngozi"
    )


def test_a_swap_without_a_counterpart_is_refused() -> None:
    lonely = Lexicon.of(
        [
            {"text": "Emma", "gender": "female", "region": "west"},
            {"text": "Ngozi", "gender": "female", "region": "africa"},
        ]
    )
    template = Template("{person}", {"person": lonely})
    space = template.space(
        [
            template.axis("person.region", "nominal"),
            template.axis("person.gender", "nominal", ("female", "male")),
        ]
    )
    with pytest.raises(PerturbationError, match="No entry has gender='male'"):
        space.variant("template", {"person.gender": "male"})


def test_swapping_a_label_must_keep_its_properties() -> None:
    space = REFUND.space([REFUND.axis("amount", "numeric", (100, 900))])
    with pytest.raises(ControlViolationError, match=r"amount\.over False -> True"):
        space.variant(next(iter(space.cases)), {"amount": 900})


def test_seeds_are_distinct_draws_at_the_baseline() -> None:
    space = refund("appeal", "amount.over", "person.gender", cases=5, seed=3)
    assert space.cases == refund("appeal", "amount.over", "person.gender", cases=5, seed=3).cases
    assert len(space.cases) == 5
    for task in space.cases.values():
        attributes = task.attributes()
        assert (attributes["appeal"], attributes["amount.over"]) == (0, False)
        assert attributes["person.gender"] == "female"
    every = refund("appeal", "amount.over", "person.gender")
    assert len(every.cases) == 3 * 2 * 3
    assert len(refund("appeal", cases=1000).cases) == 6 * 4 * 3


def test_axes_take_every_lexicon_value_in_order_on_the_declared_scale() -> None:
    appeal = REFUND.axis("appeal", "ordinal")
    region = REFUND.axis("person.region", "nominal")
    assert (appeal.values, appeal.scale) == ((0, 1, 2), "ordinal")
    assert (region.values, region.baseline, region.scale) == (("west", "africa"), "west", "nominal")
    with pytest.raises(TaskSpaceError, match="not an attribute of template Refund"):
        REFUND.axis("person.age", "nominal")
    with pytest.raises(TaskSpaceError, match="ascending order"):
        REFUND.axis("amount", "numeric")
    with pytest.raises(TaskSpaceError, match="needs numbers"):
        REFUND.axis("item", "numeric")


def test_prompt_versions_are_an_attribute_of_the_whole_prompt() -> None:
    template = Template(
        {
            "friendliness": {
                "rude": "Refund {item}. Now.",
                "neutral": "Please refund the {item}.",
                "polite": "Could you kindly refund the {item}? Thank you!",
            }
        },
        {"item": ["coat", "lamp"]},
    )
    assert template.attributes == ("item", "friendliness")
    space = template.space([template.axis("friendliness", "ordinal")])
    assert list(space.cases) == ["coat", "lamp"]
    assert space.variant("lamp").prompt.last == "Refund lamp. Now."
    polite = space.variant("lamp", {"friendliness": "polite"})
    assert polite.prompt.last == "Could you kindly refund the lamp? Thank you!"
    assert [step.axis for step in polite.steps] == ["friendliness"]
    with pytest.raises(TaskSpaceError, match="must be exactly its slots"):
        Template({"tone": {"a": "{item}", "b": "no slot"}}, {"item": ["coat"]})
    with pytest.raises(TaskSpaceError, match="free name"):
        Template({"item": {"a": "{item}"}}, {"item": ["coat"]})


def test_templates_need_exactly_their_slots_and_free_names() -> None:
    with pytest.raises(TaskSpaceError, match="must be exactly its slots"):
        Template("{a} and {b}", {"a": ["x"]})
    with pytest.raises(TaskSpaceError, match="taken by Task"):
        Template("{reference}", {"reference": ["x"]})


def test_lexicons_keep_labels_unique_and_properties_consistent(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unique"):
        Lexicon.of(["a", "a"])
    with pytest.raises(ValidationError, match="properties"):
        Lexicon.of([{"text": "a", "kind": "x"}, {"text": "b"}])
    with pytest.raises(ValidationError, match="one type"):
        Lexicon.of([1, "b"])
    with pytest.raises(ValueError, match="needs a label or a text"):
        Lexicon.of([{"kind": "x"}])
    assert Lexicon.of(PEOPLE) is PEOPLE
    path = tmp_path / "places.json"
    path.write_text(json.dumps([{"label": "nl", "text": "the Netherlands"}]), encoding="utf-8")
    assert Lexicon.load(path).entries[0].model_dump() == {
        "label": "nl",
        "text": "the Netherlands",
        "properties": {},
    }


def test_every_shipped_name_has_a_counterpart_in_every_group() -> None:
    groups = Counter(
        (entry.properties["gender"], entry.properties["region"])
        for entry in lexicons.get("names").entries
    )
    assert len(groups) == 14
    assert set(groups.values()) == {5}


def test_sources_swaps_the_name_and_keeps_the_record_and_claim() -> None:
    space = load("sources").task_space
    case = next(iter(space.cases))
    base = space.variant(case)
    swapped = space.variant(case, {"name.region": "west_africa", "name.gender": "male"})
    assert base.attributes["name"] != swapped.attributes["name"]
    for kept in ("record", "claim"):
        assert base.attributes[kept] == swapped.attributes[kept]
    assert (base.reference, space.variant(case, {"record.reliable": False}).reference) == (
        "reliable",
        "doubtful",
    )
