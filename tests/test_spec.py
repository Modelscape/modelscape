from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from modelscape import Lexicon, Template, lexicons
from modelscape.core import SpecError, TaskSpaceError
from modelscape.core.files import format_yaml, parse_scalar, parse_yaml, read_yaml
from modelscape.spec import Range, Spec
from modelscape.targets import TargetOutput
from modelscape.template import Lexical

REFUNDS = """
name: refunds
version: 2
description: Refunds follow the amount, not the customer.
system: |
  Approve refunds up to $500 and escalate larger ones.
  Reply with only a JSON object: {"decision": "approve" or "escalate"}.
prompt: |
  {person} asks for ${amount} back for a {item}. {appeal}
slots:
  person: names
  amount: [{label: 100, over: false}, {label: 900, over: true}]
  item: [coat, lamp]
  appeal: {0: "", 1: "Today, please."}
vary:
  person.gender: nominal
  appeal: ordinal
  amount.over: nominal
answer:
  field: decision
  choices: [approve, escalate]
  correct:
    amount.over: {true: escalate, false: approve}
cases: 6
"""


def test_yaml_reads_only_true_and_false_as_booleans() -> None:
    assert parse_yaml("a: yes\nb: true\nc: 2024-01-01\nd: 012\ne: 1.5\nf: -3\ng:\nh: 1e3") == {
        "a": "yes",
        "b": True,
        "c": "2024-01-01",
        "d": "012",
        "e": 1.5,
        "f": -3,
        "g": None,
        "h": "1e3",
    }


def test_yaml_is_written_with_blocks_for_text_and_short_collections_inline(
    tmp_path: Path,
) -> None:
    value = {
        "text": "one\ntwo",
        "long": " ".join(["word"] * 30),
        "quoted": ["true", "12", "", "no"],
        "rows": [{"label": 1, "ok": True}, {"label": 2, "ok": False}],
        "pairs": ("a", "b"),
    }
    written = format_yaml(value)
    assert "text: |-\n  one\n  two\n" in written
    assert "long: >-\n" in written
    assert "quoted: ['true', '12', '', 'no']" in written
    assert "- {label: 1, ok: true}" in written
    assert "pairs: [a, b]" in written
    assert format_yaml({"rows": [{"values": (0, 2)}, {"values": [0, 2]}]}) == (
        "rows:\n- {values: [0, 2]}\n- {values: [0, 2]}\n"
    )
    assert [parse_scalar(text) for text in ("true", "12", "1.5", "a: b", "[x", "yes", "007")] == [
        True,
        12,
        1.5,
        "a: b",
        "[x",
        "yes",
        "007",
    ]
    path = tmp_path / "value.yaml"
    path.write_text(written, encoding="utf-8")
    assert read_yaml(path) == {**value, "pairs": ["a", "b"]}


def test_lexicons_read_every_form_and_write_the_shortest() -> None:
    forms: list[Lexical] = [
        ["coat", "lamp"],
        [1, 2],
        {"none": "", "polite": "Please."},
        [{"text": "Emma", "gender": "female"}, {"text": "James", "gender": "male"}],
        [{"label": 100, "over": False}, {"label": 900, "text": "nine hundred", "over": True}],
    ]
    for form in forms:
        lexicon = Lexicon.of(form)
        assert lexicon.data() == form
        assert Lexicon.of(lexicon.data()) == lexicon
    with pytest.raises(ValueError, match="not the text 'coat'"):
        Lexicon.of("coat")


def test_shipped_lexicons_are_found_by_name() -> None:
    assert lexicons.available() == ("injections", "names", "pressure", "roles", "tones")
    for name in ("injections", "pressure", "roles", "tones"):
        assert lexicons.get(name).entries[0].text == ""
    assert lexicons.get("pressure").values() == (0, 1, 2, 3, 4, 5)
    groups = Counter(
        (entry.properties["gender"], entry.properties["region"])
        for entry in lexicons.get("names").entries
    )
    assert (len(groups), set(groups.values())) == (14, {5})
    with pytest.raises(ValueError, match="No lexicon is called 'nicknames'"):
        lexicons.get("nicknames")


def test_a_spec_compiles_to_a_checked_scenario() -> None:
    scenario = Spec.parse(REFUNDS).scenario()
    assert (scenario.name, scenario.version, scenario.repetitions) == ("refunds", "2", 5)
    space = scenario.task_space
    assert [axis.name for axis in space.axes] == ["person.gender", "appeal", "amount.over"]
    assert len(space.cases) == 6
    case = next(iter(space.cases))
    base = space.variant(case)
    assert base.prompt.system is not None
    assert base.prompt.system.endswith('{"decision": "approve" or "escalate"}.')
    assert base.prompt.last.endswith("$100 back for a coat.") or base.prompt.last.endswith("lamp.")
    assert space.variant(case, {"amount.over": True}).reference == "escalate"
    assert space.variant(case, {"appeal": 1}).prompt.last.endswith("Today, please.")
    assert scenario.answer(TargetOutput(text='{"decision": "escalate"}')) == "escalate"
    assert "all checked" in scenario.describe()


def test_a_spec_renders_exactly_what_the_same_template_renders() -> None:
    spec = Spec.parse(REFUNDS)
    template = Template(
        "{person} asks for ${amount} back for a {item}. {appeal}",
        {slot: spec.lexicon(slot) for slot in spec.slots},
        name="refunds",
        system=spec.system,
        reference=lambda attributes: "escalate" if attributes["amount.over"] else "approve",
    )
    axes = [
        template.axis("person.gender", "nominal"),
        template.axis("appeal", "ordinal"),
        template.axis("amount.over", "nominal"),
    ]
    ours = spec.scenario().task_space
    theirs = template.space(axes, cases=6)
    coordinates = list(theirs.coordinates.sweep())
    assert [variant.id for variant in ours.variants(coordinates)] == [
        variant.id for variant in theirs.variants(coordinates)
    ]


def test_axes_take_their_scale_values_and_baseline() -> None:
    spec = Spec.of(
        {
            **parse_yaml(REFUNDS),
            "vary": {"appeal": {"scale": "nominal", "values": [1, 0], "baseline": 1}},
            "answer": {
                "field": "decision",
                "choices": ["approve", "escalate"],
                "correct": "approve",
            },
            "design": "grid",
            "repetitions": 2,
        }
    )
    scenario = spec.scenario()
    [axis] = scenario.task_space.axes
    assert (axis.values, axis.baseline, axis.scale) == ((1, 0), 1, "nominal")
    assert scenario.design.kind == "grid"
    assert scenario.repetitions == 2


def test_a_spec_writes_itself_back_in_its_shortest_form(tmp_path: Path) -> None:
    spec = Spec.parse(REFUNDS)
    path = spec.save(tmp_path / "refunds.yaml")
    written = path.read_text(encoding="utf-8")
    assert written.startswith("name: refunds\nversion: 2\n")
    assert "  person: names\n" in written
    assert "  item: [coat, lamp]\n" in written
    assert "    amount.over: {true: escalate, false: approve}\n" in written
    assert "seed" not in written
    assert Spec.load(path) == spec


MALFORMED: list[tuple[dict[str, object], str]] = [
    ({"answer": None}, "answer: Input should be"),
    ({"vary": {}}, "vary: Dictionary should have at least 1 item"),
    ({"vary": ["appeal"]}, "vary: Input should be a valid dictionary"),
    ({"vary": {"appeal": "ordered"}}, "vary.appeal"),
    ({"vary": {"appeal": {"baseline": 0}}}, r"vary\.appeal\.Varied\.scale: Field required"),
    ({"prompt": {"a": {"x": "{person}"}, "b": {"x": "{person}"}}}, "one attribute name"),
    ({"answer": {"field": "d", "choices": ["a", "b"], "correct": "c"}}, "'c' is not one"),
    (
        {
            "answer": {
                "field": "d",
                "choices": ["a", "b"],
                "correct": {"x": {1: "a"}, "y": {1: "b"}},
            }
        },
        "exactly one attribute",
    ),
    (
        {
            "answer": {
                "field": "d",
                "choices": ["a", "b"],
                "correct": [{"then": "a"}, {"then": "b"}],
            }
        },
        "Every rule but the last needs a when",
    ),
    (
        {
            "answer": {
                "field": "d",
                "choices": ["a", "b"],
                "correct": [{"when": {"x": 1}, "then": "a"}],
            }
        },
        "The last rule gives the answer otherwise",
    ),
    ({"answer": {"field": "d", "choices": ["a", "b"], "correct": []}}, "The last rule gives"),
    (
        {"answer": {"field": "d", "choices": ["a", "b"], "correct": [{"then": "c"}]}},
        "'c' is not one",
    ),
    ({"slots": {"person": ["Emma", "Emma"]}}, "slots.person: .*unique"),
    ({"cases": 0}, "cases: Input should be greater than or equal to 1"),
    ({"slots": {"person": 5}}, "slots.person: A slot is a lexicon name, a list, a mapping, or a"),
    ({"slots": {"amount": {"from": 900, "to": 100, "step": 1}}}, "'to' must be above 'from'"),
    ({"slots": {"amount": {"from": 0, "to": 1, "step": 0}}}, "step: Input should be greater"),
    ({"slots": {"amount": {"from": 0, "to": 1, "step": 1e-4}}}, "at most 1000 numbers"),
    ({"slots": {"amount": {"from": True, "to": 2, "step": 1}}}, "from.int: Input should be"),
    ({"answer": {"choices": ["a", "b"], "correct": "a"}}, "either a field or a pattern"),
    (
        {"answer": {"field": "d", "pattern": "a", "choices": ["a", "b"], "correct": "a"}},
        "either a field or a pattern",
    ),
    ({"answer": {"pattern": "(", "choices": ["a", "b"], "correct": "a"}}, "is not valid"),
    ({"slots": {"item": [{"text": {"a": "coat"}}]}}, "needs a label, since its text"),
    ({"slots": {"item": {"coat": "coat", "lamp": {"a": "lamp"}}}}, "every text of a lexicon"),
]


@pytest.mark.parametrize(("change", "message"), MALFORMED)
def test_malformed_specs_name_every_problem(change: dict[str, object], message: str) -> None:
    with pytest.raises(SpecError, match=message):
        Spec.of({**parse_yaml(REFUNDS), **change})


def test_specs_are_checked_against_their_template_when_compiled() -> None:
    data = parse_yaml(REFUNDS)
    partial = {**data["answer"], "correct": {"amount.over": {True: "escalate"}}}
    with pytest.raises(TaskSpaceError, match=r"amount\.over=False has no answer"):
        Spec.of({**data, "answer": partial}).scenario()
    with pytest.raises(TaskSpaceError, match="not an attribute of template refunds"):
        Spec.of({**data, "vary": {"person.age": "nominal"}}).scenario()
    with pytest.raises(TaskSpaceError, match="must be exactly its slots"):
        Spec.of({**data, "prompt": "{person}"}).scenario()
    with pytest.raises(ValueError, match="No lexicon is called 'people'"):
        Spec.of({**data, "slots": {**data["slots"], "person": "people"}}).scenario()


def test_a_prompt_in_versions_is_an_attribute_to_vary(tmp_path: Path) -> None:
    data = parse_yaml(REFUNDS)
    text = data["prompt"]
    versions = {"neutral": text, "polite": f"Hello! {text} Thank you so much."}
    spec = Spec.of(
        {**data, "prompt": {"friendliness": versions}, "vary": {"friendliness": "ordinal"}}
    )
    space = spec.scenario().task_space
    case = next(iter(space.cases))
    assert space.variant(case, {"friendliness": "polite"}).prompt.last.startswith("Hello! ")
    assert Spec.load(spec.save(tmp_path / "versions.yaml")) == spec


def test_rules_give_the_first_matching_answer_or_the_answer_otherwise(tmp_path: Path) -> None:
    data = parse_yaml(REFUNDS)
    rules = [
        {"when": {"amount.over": True, "appeal": 1}, "then": "escalate"},
        {"when": {"amount.over": True}, "then": "approve"},
        {"then": "approve"},
    ]
    spec = Spec.of({**data, "design": "grid", "answer": {**data["answer"], "correct": rules}})
    scenario = spec.scenario()
    space = scenario.task_space
    answers = {
        (variant.coordinate["amount.over"], variant.coordinate["appeal"]): variant.reference
        for variant in space.variants(scenario.design.coordinates(space.coordinates))
    }
    assert answers[(True, 1)] == "escalate"
    assert answers[(True, 0)] == "approve"
    assert answers[(False, 1)] == "approve"
    assert spec.answer.rules[0].matches({"amount.over": True, "appeal": 1})
    assert not spec.answer.rules[0].matches({"amount.over": True})
    assert Spec.load(spec.save(tmp_path / "rules.yaml")) == spec
    assert "  - when: {amount.over: true, appeal: 1}\n    then: escalate\n" in spec.dump()
    assert "  - then: approve\n" in spec.dump()
    typo = [{"when": {"amount.over": "yes"}, "then": "escalate"}, {"then": "approve"}]
    with pytest.raises(TaskSpaceError, match=r"amount\.over has no value 'yes'"):
        Spec.of({**data, "answer": {**data["answer"], "correct": typo}}).scenario()


def test_a_range_holds_every_number_from_its_start_up_to_its_end(tmp_path: Path) -> None:
    data = parse_yaml(REFUNDS)
    spec = Spec.of(
        {
            **data,
            "slots": {**data["slots"], "amount": {"from": 100, "to": 1000, "step": 300}},
            "vary": {"amount": "numeric"},
            "answer": {**data["answer"], "correct": "approve"},
        }
    )
    assert spec.lexicon("amount").values() == (100, 400, 700, 1000)
    assert [entry.text for entry in spec.lexicon("amount").entries][:2] == ["100", "400"]
    assert "  amount: {from: 100, to: 1000, step: 300}\n" in spec.dump()
    assert Spec.load(spec.save(tmp_path / "range.yaml")) == spec
    assert spec.scenario().task_space.axes[0].values == (100, 400, 700, 1000)
    tenths = Range.model_validate({"from": 0, "to": 0.3, "step": 0.1})
    assert tenths.values == (0.0, 0.1, 0.2, 0.3)
    assert [entry.text for entry in tenths.lexicon().entries] == ["0", "0.1", "0.2", "0.3"]
    assert Range.model_validate({"from": 1, "to": 6, "step": 2}).values == (1, 3, 5)
    mapping = {**data["slots"], "amount": {"from": "a", "to": "b"}}
    assert Spec.of({**data, "slots": mapping}).lexicon("amount").values() == ("from", "to")


def test_rules_can_bound_a_numeric_attribute(tmp_path: Path) -> None:
    data = parse_yaml(REFUNDS)
    slots = {**data["slots"], "amount": {"from": 100, "to": 900, "step": 200}}
    rules = [
        {"when": {"amount": {"at_least": 300, "below": 500}}, "then": "approve"},
        {"when": {"amount": {"at_least": 500}}, "then": "escalate"},
        {"then": "approve"},
    ]
    spec = Spec.of(
        {
            **data,
            "slots": slots,
            "vary": {"amount": "numeric"},
            "answer": {**data["answer"], "correct": rules},
        }
    )
    scenario = spec.scenario()
    space = scenario.task_space
    answers = {
        variant.coordinate["amount"]: variant.reference
        for variant in space.variants(scenario.design.coordinates(space.coordinates))
    }
    assert answers == {
        100: "approve",
        300: "approve",
        500: "escalate",
        700: "escalate",
        900: "escalate",
    }
    assert Spec.load(spec.save(tmp_path / "bounds.yaml")) == spec
    assert "amount: {at_least: 500}" in spec.dump()
    for condition, message in [
        ({"amount": {"at_least": 1000}}, "amount has no value at least 1000"),
        ({"item": {"below": 3}}, "item has values that are not numbers"),
    ]:
        bounded = [{"when": condition, "then": "escalate"}, {"then": "approve"}]
        with pytest.raises(TaskSpaceError, match=message):
            Spec.of(
                {**data, "slots": slots, "answer": {**data["answer"], "correct": bounded}}
            ).scenario()
    for bound, message in [
        ({}, "needs at_least, below, or both"),
        ({"at_least": 5, "below": 5}, "below must be above"),
    ]:
        bounded = [{"when": {"amount": bound}, "then": "escalate"}, {"then": "approve"}]
        with pytest.raises(SpecError, match=message):
            Spec.of({**data, "answer": {**data["answer"], "correct": bounded}})


def test_trailing_whitespace_does_not_change_a_spec() -> None:
    data = parse_yaml(REFUNDS)
    assert Spec.of(data) == Spec.of({**data, "prompt": data["prompt"].strip()})


def test_texts_can_differ_per_prompt_version(tmp_path: Path) -> None:
    data = parse_yaml(REFUNDS)
    spec = Spec.of(
        {
            **data,
            "prompt": {"language": {"en": data["prompt"], "fr": f"Bonjour. {data['prompt']}"}},
            "slots": {**data["slots"], "item": {"coat": {"en": "coat", "fr": "manteau"}}},
            "vary": {"language": "nominal"},
        }
    )
    space = spec.scenario().task_space
    case = next(iter(space.cases))
    assert "for a coat." in space.variant(case).prompt.last
    assert "for a manteau." in space.variant(case, {"language": "fr"}).prompt.last
    assert Spec.load(spec.save(tmp_path / "languages.yaml")) == spec
    missing = {**data["slots"], "item": {"coat": {"en": "coat"}}}
    with pytest.raises(
        TaskSpaceError, match=r"needs one text for each prompt version \['en', 'fr'\]"
    ):
        Spec.of({**spec.model_dump(), "slots": missing}).scenario()
    with pytest.raises(TaskSpaceError, match="has texts per version, but the prompt has none"):
        Spec.of({**data, "slots": missing}).scenario()


def test_groups_name_the_cases_whose_attributes_match() -> None:
    data = parse_yaml(REFUNDS)
    scenario = Spec.of(
        {**data, "vary": {"appeal": "ordinal"}, "groups": {"large": {"amount": {"at_least": 500}}}}
    ).scenario()
    large = scenario.groups["large"]
    assert large
    assert all(scenario.task_space.cases[case].attributes()["amount.over"] for case in large)
    assert set(large) < set(scenario.task_space.cases)
    with pytest.raises(TaskSpaceError, match=r"groups\.huge: no case matches"):
        Spec.of({**data, "groups": {"huge": {"amount": {"at_least": 5000}}}}).scenario()


def test_a_pattern_reads_the_answer_from_free_text() -> None:
    data = parse_yaml(REFUNDS)
    answer = {"pattern": r"\b(approve|escalate)\b", "choices": ["approve", "escalate"]}
    spec = Spec.of({**data, "answer": {**data["answer"], **answer, "field": None}})
    read = spec.scenario().answer
    assert read(TargetOutput(text="I would escalate this.")) == "escalate"
    assert read(TargetOutput(text="Refund it.")) is None
    numbers = Spec.of(
        {**data, "answer": {"pattern": "[0-9]", "choices": [1, 2], "correct": 1}}
    ).scenario()
    assert numbers.answer(TargetOutput(text="Option 2.")) == 2
    assert numbers.answer(TargetOutput(text="Option 3.")) is None
