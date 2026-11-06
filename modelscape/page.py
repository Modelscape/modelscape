"""Scenarios and reports as self-contained HTML pages: review a scenario, then read its report."""

from __future__ import annotations

import html
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

from pydantic import JsonValue

from modelscape.analysis import Results
from modelscape.analysis.scorecard import axis_role
from modelscape.core.coordinates import same_value
from modelscape.core.measurements import DifferenceMeasurement, PointMeasurement
from modelscape.core.observations import Observation
from modelscape.core.serialization import canonical_json
from modelscape.core.tasks import Variant
from modelscape.core.text import word_diff
from modelscape.report import Report
from modelscape.scenario import Scenario
from modelscape.storage import MemoryStore, SQLiteStore, Store

SCRIPT = Path(__file__).parent / "static" / "page.js"
DOCUMENT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
</head>
<body style="margin:0">{body}</body>
</html>
"""

Outputs = Results | Store | str | os.PathLike[str]


class Page:
    """One self-contained HTML page that needs no server. In a notebook it shows inline."""

    __slots__ = ("html", "title")

    def __init__(self, title: str, data: JsonValue) -> None:
        self.title = title
        self.html = _fragment(data)

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the page as a standalone HTML file and return its path."""
        target = Path(path)
        target.write_text(
            DOCUMENT.format(title=html.escape(self.title), body=self.html), encoding="utf-8"
        )
        return target

    def _repr_html_(self) -> str:
        return self.html


class ScenarioPage(Page):
    """A scenario as one HTML page, to review before anything runs.

    Shows every axis with its role, and every variant of every case with its correct answer and
    the words it changes in the prompt.
    """

    __slots__ = ()

    def __init__(self, scenario: Scenario) -> None:
        super().__init__(f"{scenario.name} {scenario.version} · modelscape", _review(scenario))


class ReportPage(Page):
    """A report as one HTML page; click any number to read the outputs behind it.

    ``outputs`` is the run's ``Results``, a store, or a store file. The page embeds only the
    outputs behind the report's numbers.
    """

    __slots__ = ()

    def __init__(
        self, report: Report | str | os.PathLike[str], outputs: Outputs | None = None
    ) -> None:
        loaded = report if isinstance(report, Report) else Report.load(report)
        dumped: JsonValue = loaded.model_dump(mode="json")
        if isinstance(outputs, str | os.PathLike):
            path = Path(outputs)
            if not path.is_file():
                raise FileNotFoundError(f"No store at {path}.")
            with SQLiteStore(path) as store:
                data = _embed(dumped, store)
        else:
            data = _embed(dumped, _memory(outputs) if isinstance(outputs, Results) else outputs)
        super().__init__(f"{loaded.scenario.name} {loaded.scenario.version} · modelscape", data)


def _review(scenario: Scenario) -> JsonValue:
    space = scenario.task_space
    coordinates = scenario.design.coordinates(space.coordinates)
    cases = {case: [space.variant(case, at) for at in coordinates] for case in space.cases}
    answers = {
        (variant.case_id, variant.coordinate): canonical_json(variant.reference)
        for variants in cases.values()
        for variant in variants
    }
    baselines = {case: space.variant(case) for case in cases}
    system = next(iter(baselines.values())).prompt.system
    return {
        "scenario": {
            "name": scenario.name,
            "version": scenario.version,
            "description": scenario.description,
            "repetitions": scenario.repetitions,
            "system": system,
            "axes": [
                {
                    "name": axis.name,
                    "scale": axis.scale,
                    "role": axis_role(axis.name, coordinates, list(cases), answers),
                    "values": list(axis.values),
                    "baseline": axis.baseline,
                }
                for axis in space.axes
            ],
            "cases": [
                {
                    "case": case,
                    "reference": baselines[case].reference,
                    "variants": [
                        _variant(variant, baselines[case], system) for variant in variants
                    ],
                }
                for case, variants in cases.items()
            ],
        }
    }


def _variant(variant: Variant, baseline: Variant, system: str | None) -> JsonValue:
    shown: dict[str, JsonValue] = {
        "changed": [
            [axis, value]
            for axis, value in variant.coordinate.items()
            if not same_value(value, baseline.coordinate[axis])
        ],
        "reference": variant.reference,
        "parts": word_diff(baseline.prompt.last, variant.prompt.last),
    }
    if variant.prompt.system != system:
        shown["system"] = variant.prompt.system
    return shown


def _memory(results: Results) -> Store:
    store = MemoryStore()
    store.put(
        [
            *results.variants,
            *results.observations,
            *results.point_measurements,
            *results.difference_measurements,
        ]
    )
    return store


def _embed(report: JsonValue, store: Store | None) -> JsonValue:
    if store is None:
        return {"report": _replace(report, lambda _: []), "outputs": None}
    ids = set(_measurements(report))
    points = store.get(PointMeasurement, ids)
    pairs = store.get(DifferenceMeasurement, ids)
    wanted = {point.observation_id for point in points.values()}
    for pair in pairs.values():
        wanted |= {pair.start_observation_id, pair.end_observation_id}
    observations = sorted(
        store.get(Observation, wanted).values(),
        key=lambda item: (item.case_id, item.coordinate.key, item.target.name, item.repetition),
    )
    order = {
        key: number
        for number, key in enumerate(dict.fromkeys(item.variant_id for item in observations))
    }
    variants = store.get(Variant, order)
    index = {item.id: number for number, item in enumerate(observations)}

    def behind(measured: list[str]) -> JsonValue:
        found: dict[int, float | None] = {}
        for key in measured:
            if key in points:
                found[index[points[key].observation_id]] = points[key].value
            elif key in pairs:
                for observation in (pairs[key].start_observation_id, pairs[key].end_observation_id):
                    found.setdefault(index[observation], None)
        return [[number, found[number]] for number in sorted(found)]

    return {
        "report": _replace(report, behind),
        "outputs": {
            "observations": [
                {
                    "target": item.target.name,
                    "repetition": item.repetition,
                    "text": item.output.as_text(),
                    "error": None if item.output.error is None else item.output.error.message,
                    "variant": order[item.variant_id],
                }
                for item in observations
            ],
            "variants": [
                {
                    "case": item.case_id,
                    "coordinate": dict(item.coordinate),
                    "prompt": item.prompt.model_dump(mode="json"),
                    "reference": item.reference,
                }
                for item in (variants[key] for key in order)
            ],
        },
    }


def _measurements(value: JsonValue) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "measurement_ids" and isinstance(item, list):
                yield from (str(entry) for entry in item)
            else:
                yield from _measurements(item)
    elif isinstance(value, list):
        for item in value:
            yield from _measurements(item)


def _replace(value: JsonValue, behind: Callable[[list[str]], JsonValue]) -> JsonValue:
    if isinstance(value, dict):
        return {
            "outputs" if key == "measurement_ids" else key: (
                behind([str(entry) for entry in item])
                if key == "measurement_ids" and isinstance(item, list)
                else _replace(item, behind)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace(item, behind) for item in value]
    return value


def _fragment(data: JsonValue) -> str:
    if not SCRIPT.is_file():
        raise FileNotFoundError(
            "The page is not built: npm --prefix page ci && npm --prefix page run build"
        )
    payload = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    script = SCRIPT.read_text(encoding="utf-8").replace("</script", "<\\/script")
    return f'<div><script type="application/json">{payload}</script></div><script>{script}</script>'
