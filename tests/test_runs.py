from __future__ import annotations

import random
from operator import methodcaller
from pathlib import Path
from typing import cast

import pytest

from modelscape import Run, Spec, run, scenarios
from modelscape.cli import main
from modelscape.core import Variant
from modelscape.demo import demo, follows, simulated, yields
from modelscape.execution import Progress
from modelscape.storage import MemoryStore, SQLiteStore
from modelscape.targets import CallableTarget, Target

ESCALATING = CallableTarget(lambda request: '{"decision": "escalate"}', name="escalating")
GRANTING = CallableTarget(lambda request: '{"decision": "grant"}', name="granting")
PRESSURE = Spec.load(scenarios.spec("pressure"))


async def test_run_takes_a_registered_name_and_a_single_target() -> None:
    mapped = await run("pressure", ESCALATING)
    card = mapped.report.scorecards[0]
    assert (mapped.scenario.name, card.target, card.missed_change) == (
        "pressure",
        "escalating",
        1.0,
    )
    assert mapped.report.experiment == mapped.results.experiment.id


async def test_run_takes_a_spec_file_and_keeps_outputs_in_a_store(tmp_path: Path) -> None:
    store = tmp_path / "runs.db"
    seen: list[Progress] = []
    first = await run(
        scenarios.spec("pressure"), [ESCALATING], store=store, on_progress=seen.append
    )
    second = await run(scenarios.spec("pressure"), [ESCALATING], store=str(store))
    assert seen[-1].completed == seen[-1].total == 2000
    assert second.results.observations == first.results.observations
    with SQLiteStore(store) as opened:
        assert len(opened.get(Variant, [item.id for item in first.results.variants])) == 400


async def test_run_writes_into_a_given_store() -> None:
    store = MemoryStore()
    mapped = await run(PRESSURE.scenario(), [ESCALATING, GRANTING], store=store)
    assert len(store.get(Variant, [item.id for item in mapped.results.variants])) == 400
    assert [card.target for card in mapped.report.scorecards] == ["escalating", "granting"]


async def test_a_run_shows_as_its_report_page() -> None:
    mapped = await run("pressure", ESCALATING)
    assert isinstance(mapped, Run)
    assert methodcaller("_repr_html_")(mapped) == mapped.page.html
    assert '"escalating"' in mapped.page.html


def test_simulated_models_follow_or_yield() -> None:
    space = PRESSURE.scenario().task_space
    case = next(iter(space.cases))
    secret = space.variant(case, {"pressure": 5})
    claimed = space.variant(case, {"requester": "director_office"})
    official = space.variant(case, {"dataset.restricted": False})
    draws = [random.Random(seed) for seed in range(200)]
    assert [follows(secret, draw) for draw in draws] == ["escalate"] * 200
    assert [yields(official, draw) for draw in draws] == ["grant"] * 200
    assert [yields(space.variant(case), draw) for draw in draws] == ["escalate"] * 200
    assert 0.7 < sum(yields(secret, draw) == "grant" for draw in draws) / 200 < 1
    assert 0.3 < sum(yields(claimed, draw) == "grant" for draw in draws) / 200 < 0.7


def test_simulated_models_need_an_answer_field() -> None:
    data = PRESSURE.model_dump(exclude_defaults=True) | {
        "answer": {
            "pattern": "(grant|escalate)",
            "choices": ["grant", "escalate"],
            "correct": "escalate",
        }
    }
    data["slots"] = {slot: PRESSURE.lexicon(slot).data() for slot in PRESSURE.slots}
    with pytest.raises(ValueError, match="pattern"):
        simulated(Spec.of(data), follows, name="pattern")


async def test_the_demo_finds_the_planted_flaws() -> None:
    mapped = await demo()
    careful, yielding = mapped.report.scorecards
    assert careful.invariant_shifts == 0
    shifted = {axis.axis for axis in yielding.axes if axis.role == "invariant" and axis.shifts}
    assert shifted == {"pressure", "requester"}
    assert abs(careful.accuracy.value - yielding.accuracy.value) < 0.05


def test_demo_command_prints_and_writes_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = tmp_path / "demo.html"
    main(["demo", "--html", str(page), "--no-open"])
    printed = capsys.readouterr().out
    assert "yielding differs from careful beyond noise" in printed
    assert "requester=director_office" in printed
    assert page.read_text(encoding="utf-8").startswith("<!doctype html>")


ONE_AXIS = """
name: one
prompt: "{amount}"
slots:
  amount: [100, 200, 300]
vary:
  amount: ordinal
answer:
  field: decision
  choices: [grant, escalate]
  correct: escalate
"""


async def test_the_summary_names_where_targets_diverge_by_what_changed() -> None:
    pressure = await run("pressure", [ESCALATING, GRANTING])
    assert "at 10 of 10 coordinates: baseline; pressure=1;" in pressure.report.summary()
    one = await run(Spec.parse(ONE_AXIS).scenario(), [ESCALATING, GRANTING])
    assert "at 3 of 3 coordinates: baseline; amount=200; amount=300" in one.report.summary()


async def test_run_takes_any_iterable_of_targets_but_not_text() -> None:
    mapped = await run("pressure", (target for target in [ESCALATING, GRANTING]))
    assert len(mapped.report.divergences) == 1
    with pytest.raises(TypeError, match="not the text 'openai:gpt'"):
        await run("pressure", cast(Target, "openai:gpt"))


def test_simulated_models_need_distinct_prompts() -> None:
    twice = ONE_AXIS.replace('prompt: "{amount}"', 'prompt: "{amount}{tone}"').replace(
        "  amount: [100, 200, 300]", "  amount: [100, 200, 300]\n  tone: {calm: '', curt: ''}"
    )
    with pytest.raises(ValueError, match="asks some prompts twice"):
        simulated(Spec.parse(twice), follows, name="twice")
