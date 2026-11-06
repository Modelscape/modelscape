from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import cache
from pathlib import Path

import pytest

from modelscape import Runner
from modelscape.cli import main
from modelscape.core import RequirementError
from modelscape.gate import Requirement, check
from modelscape.report import Report
from modelscape.scenarios import load
from modelscape.targets import CallableTarget, TargetOutput

TARGETS = {
    "escalating": CallableTarget(lambda request: '{"decision": "escalate"}', name="escalating"),
    "granting": CallableTarget(lambda request: '{"decision": "grant"}', name="granting"),
    "chatty": CallableTarget(lambda request: "Happy to help!", name="chatty"),
}
GROUPED = replace(load("pressure"), groups={"small": ("informants/arms", "covert/sanctions")})


@cache
def report(*names: str) -> Report:
    experiment = GROUPED.experiment([TARGETS[name] for name in names])
    return GROUPED.report(asyncio.run(Runner().run(experiment)))


def test_requirements_read_quantity_comparison_and_threshold() -> None:
    requirement = Requirement.parse(" spurious_change <= 0.05 ")
    assert (requirement.quantity, requirement.comparison, requirement.threshold) == (
        "spurious_change",
        "<=",
        0.05,
    )
    assert str(Requirement.parse("invariant_shifts==0")) == "invariant_shifts==0"
    scoped = Requirement.parse("sensitive: accuracy>=0.9")
    assert (scoped.group, str(scoped)) == ("sensitive", "sensitive:accuracy>=0.9")
    for text in ("precision>=0.9", "accuracy=>0.9", "accuracy>=high", "all:divergences==0"):
        with pytest.raises(RequirementError, match="Cannot read requirement"):
            Requirement.parse(text)


def test_every_scorecard_must_meet_every_requirement() -> None:
    mapped = report("escalating")
    met = [Requirement.parse(text) for text in ("accuracy>=0.9", "invariant_shifts==0")]
    assert check(mapped, met) == []
    assert check(mapped, [Requirement.parse("missed_change<=0.5")]) == [
        "escalating all: missed_change is 1, required <= 0.5",
        "escalating small: missed_change is 1, required <= 0.5",
    ]


def test_requirements_can_be_limited_to_a_group_and_to_targets() -> None:
    mapped = report("escalating", "granting")
    small = [Requirement.parse("small:accuracy>=0.9")]
    assert check(mapped, small) == ["granting small: accuracy is 0, required >= 0.9"]
    assert check(mapped, small, targets=["escalating"]) == []
    assert check(mapped, [Requirement.parse("divergences==0")], targets=["escalating"]) == []
    with pytest.raises(RequirementError, match="has groups all, small"):
        check(mapped, [Requirement.parse("large:accuracy>=0.9")])
    with pytest.raises(RequirementError, match="not in the report"):
        check(mapped, small, targets=["missing"])


def test_divergences_count_coordinates_where_targets_differ_beyond_noise() -> None:
    mapped = report("escalating", "granting")
    assert check(mapped, [Requirement.parse("divergences==0")]) == [
        "granting versus escalating: divergences is 10, required == 0"
    ]
    assert check(mapped, [Requirement.parse("divergences<=10")]) == []


def test_check_command_exits_with_failure_when_a_requirement_is_missed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "report.json"
    path.write_text((report("escalating")).model_dump_json(), encoding="utf-8")
    main(["check", str(path), "--require", "accuracy>=0.9"])
    assert "All requirements met: accuracy>=0.9" in capsys.readouterr().out
    with pytest.raises(SystemExit) as failed:
        main(["check", str(path), "--require", "accuracy>=0.9", "--require", "missed_change<0.1"])
    assert failed.value.code == 1
    assert "escalating all: missed_change is 1, required < 0.1" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not in the report"):
        main(["check", str(path), "--require", "accuracy>=0.9", "--gate-target", "missing"])


def test_run_command_fails_on_a_missed_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def escalating(spec: str, max_tokens: int) -> CallableTarget:
        return CallableTarget(
            lambda request: TargetOutput(text='{"decision": "escalate"}'), name=spec
        )

    monkeypatch.setattr("modelscape.cli.target", escalating)
    arguments = ["run", "pressure", "--target", "a", "--store", str(tmp_path / "runs.db")]
    main([*arguments, "--require", "accuracy>=0.9"])
    with pytest.raises(SystemExit) as failed:
        main([*arguments, "--require", "missed_change<=0"])
    assert failed.value.code == 1
    with pytest.raises(SystemExit, match="Cannot read requirement"):
        main([*arguments, "--require", "accuracy"])


def test_answered_is_the_share_of_outputs_with_a_readable_answer() -> None:
    mapped = report("escalating", "chatty")
    assert [card.answered for card in mapped.scorecards] == [1.0, 1.0, 0.0, 0.0]
    assert check(mapped, [Requirement.parse("answered>=0.95")]) == [
        "chatty all: answered is 0, required >= 0.95",
        "chatty small: answered is 0, required >= 0.95",
    ]


def test_compare_lines_up_reports_and_selects_targets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "report.json"
    (report("escalating", "granting")).save(path)
    main(["compare", str(path)])
    table = capsys.readouterr().out.splitlines()
    assert table[0].split() == [
        "scenario",
        "group",
        "target",
        "accuracy",
        "answered",
        "spurious",
        "missed",
        "invariant",
        "shifts",
    ]
    assert table[1].split() == [
        "pressure",
        "4",
        "all",
        "escalating",
        "1.00",
        "1.00",
        "0.00",
        "1.00",
        "0",
    ]
    main(["compare", str(path), str(path), "--require", "small:accuracy>=0.9"])
    selected = capsys.readouterr().out
    assert "Meets small:accuracy>=0.9: escalating" in selected
    assert "  pressure granting small: accuracy is 0, required >= 0.9" in selected
    with pytest.raises(SystemExit, match="No report has groups large"):
        main(["compare", str(path), "--require", "large:accuracy>=0.9"])
