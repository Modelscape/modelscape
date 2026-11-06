from __future__ import annotations

import asyncio
import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from modelscape import ReportPage, Results, Runner, ScenarioPage
from modelscape.cli import main
from modelscape.page import Page
from modelscape.report import Report
from modelscape.storage import SQLiteStore
from tests.helpers import FAST
from tests.switch import SCENARIO, correct, model, swayed

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
HOSTILE = "</script><script>alert(1)</script>"


@pytest.fixture
async def mapped(tmp_path: Path) -> tuple[Results, Report, Path]:
    targets = [model(correct, "ideal"), model(swayed, "swayed")]
    with SQLiteStore(tmp_path / "runs.db") as store:
        results = await Runner(store=store).run(SCENARIO.experiment(targets, FAST))
    report = SCENARIO.report(results)
    report.save(tmp_path / "report.json")
    return results, report, tmp_path


def embedded(page: Page) -> dict[str, Any]:
    payload = page.html.split('<script type="application/json">')[1].split("</script>")[0]
    return json.loads(payload)


def test_a_page_without_outputs_carries_the_report_script_and_styles(
    mapped: tuple[Results, Report, Path],
) -> None:
    _, report, folder = mapped
    page = ReportPage(folder / "report.json")
    data = embedded(page)
    assert data["outputs"] is None
    assert data["report"]["experiment"] == report.experiment
    assert "measurement_ids" not in page.html
    assert ".ms-inspector" in page.html


def behind(page: ReportPage, outputs: list[list[Any]]) -> list[dict[str, Any]]:
    embedded_outputs = embedded(page)["outputs"]
    found: list[dict[str, Any]] = []
    for index, score in outputs:
        observation = embedded_outputs["observations"][index]
        variant = embedded_outputs["variants"][observation["variant"]]
        found.append({**observation, **variant, "score": score})
    return found


def test_a_shift_embeds_the_outputs_on_both_sides(mapped: tuple[Results, Report, Path]) -> None:
    results, report, _ = mapped
    page = ReportPage(report, results)
    shift = next(
        shift
        for card in embedded(page)["report"]["scorecards"]
        if card["target"] == "ideal"
        for axis in card["axes"]
        for shift in axis["shifts"]
    )["transition"]
    found = behind(page, shift["outputs"])
    assert len(found) == shift["observations"]
    assert {json.dumps(item["coordinate"]) for item in found} == {
        json.dumps(shift["start"]),
        json.dumps(shift["end"]),
    }
    assert {item["target"] for item in found} == {"ideal"}
    assert all(item["prompt"] and item["score"] is None for item in found)


def test_an_accuracy_embeds_its_scores(mapped: tuple[Results, Report, Path]) -> None:
    results, report, _ = mapped
    page = ReportPage(report, results)
    point = embedded(page)["report"]["scorecards"][0]["axes"][0]["accuracy"][0]
    found = behind(page, point["outputs"])
    assert len(found) == point["observations"]
    assert {item["score"] for item in found} == {1.0}


def test_outputs_read_from_results_a_store_or_its_file(
    mapped: tuple[Results, Report, Path],
) -> None:
    results, report, folder = mapped
    from_results = embedded(ReportPage(report, results))
    from_path = embedded(ReportPage(report, folder / "runs.db"))
    with SQLiteStore(folder / "runs.db") as store:
        from_store = embedded(ReportPage(report, store))
    assert from_results == from_path == from_store
    with pytest.raises(FileNotFoundError, match="No store"):
        ReportPage(report, folder / "missing.db")


async def test_model_outputs_cannot_close_the_embedded_data() -> None:
    hostile = model(lambda _: HOSTILE, "hostile")
    results = await Runner().run(SCENARIO.experiment([hostile], FAST))
    page = ReportPage(SCENARIO.report(results), results)
    assert HOSTILE not in page.html
    texts = {item["text"] for item in embedded(page)["outputs"]["observations"]}
    assert texts == {HOSTILE}


def test_view_writes_a_standalone_page_next_to_the_report(
    mapped: tuple[Results, Report, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, folder = mapped
    main(["view", str(folder / "report.json"), "--store", str(folder / "runs.db"), "--no-open"])
    written = folder / "report.html"
    assert capsys.readouterr().out.strip() == str(written)
    document = written.read_text(encoding="utf-8")
    assert document.startswith("<!doctype html>")
    assert "<title>switch 1 · modelscape</title>" in document
    assert '<body style="margin:0">' in document


HOSTILE_SPEC = f"""
name: hostile
prompt: 'Release the {{marker}} file.'
slots:
  marker:
  - {{label: secret, text: '{HOSTILE}', classification: SECRET}}
  - {{label: official, text: OFFICIAL, classification: OFFICIAL}}
vary:
  marker.classification: nominal
answer:
  field: decision
  choices: [grant, deny]
  correct:
    marker.classification: {{SECRET: deny, OFFICIAL: grant}}
"""


def test_a_scenario_page_shows_every_variant_with_its_role_and_answer() -> None:
    scenario = embedded(ScenarioPage(SCENARIO))["scenario"]
    assert scenario["name"] == "switch"
    assert scenario["repetitions"] == SCENARIO.repetitions
    assert {axis["name"]: axis["role"] for axis in scenario["axes"]} == {
        "strength": "causal",
        "style": "invariant",
    }
    assert [item["case"] for item in scenario["cases"]] == ["c0", "c1", "c2"]
    shown = [variant for item in scenario["cases"] for variant in item["variants"]]
    assert len(shown) == len(list(SCENARIO.variants()))
    baseline, *changed = scenario["cases"][0]["variants"]
    assert baseline["changed"] == []
    assert {kind for _, kind in baseline["parts"]} == {"same"}
    assert all(len(variant["changed"]) == 1 for variant in changed)
    assert {variant["reference"] for variant in changed} == {"low", "high"}


def test_review_writes_the_page_next_to_the_spec_and_escapes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "hostile.yaml"
    spec.write_text(HOSTILE_SPEC, encoding="utf-8")
    main(["review", str(spec), "--no-open"])
    written = tmp_path / "hostile.html"
    assert capsys.readouterr().out.strip() == str(written)
    document = written.read_text(encoding="utf-8")
    assert "<title>hostile 1 · modelscape</title>" in document
    assert HOSTILE not in document
    assert document.count('<script type="application/json">') == 1


def test_review_of_a_shipped_scenario_writes_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    main(["review", "pressure", "--no-open", "--html", "review.html"])
    assert capsys.readouterr().out.strip() == "review.html"
    main(["review", "pressure", "--no-open"])
    assert capsys.readouterr().out.strip() == "pressure.html"
    assert (tmp_path / "pressure.html").is_file()


PLANTED = {
    "access": {"role"},
    "purchases": {"office.location"},
    "records": {"language"},
    "injection": {"injection"},
}


@pytest.mark.parametrize("name", PLANTED)
def test_each_demo_page_shows_exactly_its_planted_flaw(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", [str(EXAMPLES), *sys.path])
    demo = import_module("demo")
    monkeypatch.setattr(demo, "NAMES", (name,))
    demo.pages(tmp_path)
    page = (tmp_path / f"{name}.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert page.count('<script type="application/json">') == 1
    assert "<th>model-b</th>" in page
    mapped = asyncio.run(demo.run(demo.example(name)))
    shifted = {
        (card.target, axis.axis)
        for card in mapped.report.scorecards
        for axis in card.axes
        if axis.role == "invariant" and axis.shifts
    }
    assert shifted == {("model-b", axis) for axis in PLANTED[name]}
