from __future__ import annotations

from dataclasses import replace

import pytest

from modelscape import json_field, json_reply
from modelscape.core import AnalysisError, Identity
from modelscape.storage import MemoryStore
from modelscape.targets import TargetOutput
from tests.switch import (
    NOISY,
    SCENARIO,
    correct,
    late,
    mapped,
    model,
    noisy,
    stubborn,
    swayed,
)


def test_json_field_reads_one_field_of_the_reply_and_rejects_other_values() -> None:
    verdict = json_field("verdict", ("escalate", "close"))
    assert verdict(TargetOutput(text='Done. {"verdict": "close", "reason": "ok"}')) == "close"
    assert verdict(TargetOutput(text='{"verdict": "benign"}')) is None
    assert verdict(TargetOutput(text='{"verdict": ["close"]}')) is None
    assert verdict(TargetOutput(text="close")) is None
    assert json_field("level")(TargetOutput(text='{"level": 3}')) == 3
    assert json_field("level")(TargetOutput(text='{"level": NaN}')) is None
    assert json_reply(TargetOutput(text="[1, 2]")) == {}
    assert json_reply(TargetOutput(structured={"level": 3})) == {"level": 3}


def test_json_field_counts_a_value_as_answered_only_if_it_scores_as_its_choice() -> None:
    flag = json_field("flag", (True, False))
    assert flag(TargetOutput(text='{"flag": 1}')) is None
    assert flag(TargetOutput(text='{"flag": false}')) is False
    level = json_field("level", (1, 2))
    assert level(TargetOutput(text='{"level": true}')) is None
    assert level(TargetOutput(text='{"level": 2}')) == 2


def test_every_scenario_shares_correctness_and_answer_change() -> None:
    experiment = SCENARIO.experiment([model(correct, "ideal")])
    assert [metric.identity.name for metric in experiment.point_metrics] == [
        "correct",
        "answered",
    ]
    assert [measure.identity.name for measure in experiment.difference_measures] == [
        "answer_change"
    ]
    assert experiment.record.scenario == Identity(name="switch", version="1")


async def test_an_ideal_target_scores_perfectly() -> None:
    _, report = await mapped(model(correct, "ideal"))
    card = report.scorecards[0]
    assert (card.accuracy.value, card.spurious_change, card.missed_change) == (1.0, 0.0, 0.0)
    assert {axis.axis: axis.role for axis in card.axes} == {
        "strength": "causal",
        "style": "invariant",
    }
    shifts = {axis.axis: [item.transition.end_value for item in axis.shifts] for axis in card.axes}
    assert shifts == {"strength": [2], "style": []}


async def test_a_target_that_ignores_the_cause_misses_every_change() -> None:
    _, report = await mapped(model(stubborn, "stubborn"))
    card = report.scorecards[0]
    assert (card.accuracy.value, card.spurious_change, card.missed_change) == (1.0, 0.0, 1.0)


async def test_a_target_swayed_by_tone_changes_spuriously() -> None:
    _, report = await mapped(model(swayed, "swayed"))
    card = report.scorecards[0]
    assert card.spurious_change == pytest.approx(0.5)
    style = next(axis for axis in card.axes if axis.axis == "style")
    assert [item.transition.end_value for item in style.shifts] == ["formal"]


async def test_thresholds_compare_where_answers_flip_with_where_they_should() -> None:
    _, report = await mapped(
        model(correct, "ideal"), model(late, "late"), model(stubborn, "stubborn")
    )
    ideal, late_flip, never = (
        {axis.axis: axis.threshold for axis in card.axes}
        for card in report.scorecards
        if card.group == "all"
    )
    assert ideal["style"] is None
    assert ideal["strength"] is not None
    assert late_flip["strength"] is not None
    assert never["strength"] is not None
    assert ideal["strength"].reference == late_flip["strength"].reference == 1.5
    assert ideal["strength"].offset is not None
    assert ideal["strength"].offset.value == pytest.approx(0.0, abs=1e-9)
    assert late_flip["strength"].flip is not None
    assert late_flip["strength"].flip.value == pytest.approx(2.5, abs=0.01)
    assert ideal["strength"].width is not None
    assert ideal["strength"].width.value < 1
    assert (never["strength"].offset, never["strength"].width) == (None, None)
    assert "flips at 1.50 [1.50, 1.50], correct 1.50" in report.summary()
    assert "flips: none within the axis, correct 1.50" in report.summary()


async def test_a_noisy_threshold_has_an_interval_around_the_correct_flip() -> None:
    _, report = await mapped(noisy(correct, "noisy"), scenario=NOISY)
    threshold = report.scorecards[0].axes[0].threshold
    assert threshold is not None
    assert threshold.cases == 6
    assert threshold.observations == 6 * 4 * 8
    flip = threshold.flip
    assert flip is not None
    assert flip.lower is not None
    assert flip.upper is not None
    assert flip.lower < 1.5 < flip.upper


async def test_groups_get_their_own_scorecards() -> None:
    _, report = await mapped(model(correct, "ideal"))
    assert [(card.group, card.cases) for card in report.scorecards] == [
        ("all", ("c0", "c1", "c2")),
        ("first", ("c0",)),
    ]


async def test_divergence_locates_where_targets_differ_beyond_noise() -> None:
    results, report = await mapped(
        model(correct, "reference"), model(swayed, "swayed"), model(correct, "copy")
    )
    swayed_divergence, copy_divergence = report.divergences
    assert (swayed_divergence.first, swayed_divergence.second) == ("reference", "swayed")
    assert [dict(item.transition.end) for item in swayed_divergence.candidates] == [
        {"strength": 0, "style": "formal"}
    ]
    assert copy_divergence.candidates == ()
    assert all(item.excess and item.excess.value == 0 for item in copy_divergence.contrasts)
    with pytest.raises(AnalysisError, match="experiment order"):
        results.divergence("answer_change", "swayed", "reference")


async def test_run_to_run_noise_alone_is_not_spurious_change() -> None:
    results, report = await mapped(noisy(correct, "noisy"), scenario=NOISY)
    card = report.scorecards[0]
    assert card.spurious_change == pytest.approx(0.0, abs=0.1)
    assert all(axis.shifts == () or axis.role == "causal" for axis in card.axes)
    raw = results.profile("style", "answer_change").baseline[1].between
    assert raw is not None
    assert raw.value > 0.25


async def test_equally_noisy_models_do_not_diverge_but_a_shifted_one_does() -> None:
    _, report = await mapped(
        noisy(correct, "reference"),
        noisy(correct, "same"),
        noisy(swayed, "swayed"),
        scenario=NOISY,
    )
    same, shifted = report.divergences
    assert same.candidates == ()
    assert [dict(item.transition.end) for item in shifted.candidates] == [
        {"strength": 0, "style": "formal"}
    ]


async def test_adding_a_model_reuses_the_stored_outputs_of_the_others() -> None:
    store = MemoryStore()
    calls: list[str] = []
    await mapped(model(correct, "earlier", calls), store=store)
    _, report = await mapped(
        model(correct, "earlier", calls), model(swayed, "later", calls), store=store
    )
    assert calls.count("earlier") == calls.count("later") == 5 * 3 * 4
    assert [(item.first, item.second) for item in report.divergences] == [("earlier", "later")]


def test_a_new_scenario_version_never_reuses_measurements() -> None:
    first = SCENARIO.experiment([model(correct, "ideal")])
    second = replace(SCENARIO, version="2").experiment([model(correct, "ideal")])
    assert first.point_metrics[0].identity != second.point_metrics[0].identity
    assert first.difference_measures[0].identity != second.difference_measures[0].identity
