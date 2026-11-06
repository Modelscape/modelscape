"""The scenarios of builder.ipynb, the simulated models they are mapped on, and their pages.

``uv run python examples/demo.py`` writes one report page per scenario into ``examples/pages``.
"""

from __future__ import annotations

import asyncio
import html
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from pydantic import JsonValue

from modelscape import (
    AxisScore,
    CallableTarget,
    Report,
    ReportPage,
    Runner,
    Scenario,
    Spec,
    TargetRequest,
    Variant,
)
from modelscape.builder import Builder

SPECS = Path(__file__).parent / "specs"
NAMES = ("access", "purchases", "records", "injection")
NOISE = 0.03
COMPLIANCE = {"none": 0.0, "claim": 0.1, "authorization": 0.4, "instruction": 0.7, "override": 0.9}
STYLE = (
    "body{margin:0;background:#fff;color:#1c1917;color-scheme:light}"
    ".demo{max-width:1040px;margin:0 auto;padding:2rem 1rem;font:15px/1.6 system-ui,sans-serif}"
    ".demo h1{margin:0 0 .5rem;font-size:1.6rem}.demo>table{border-collapse:collapse}"
    ".demo>table th,.demo>table td{padding:.4rem .75rem;border-bottom:1px solid #e7e5e4;"
    "text-align:left}"
)

Behavior = Callable[[Variant, random.Random], JsonValue]


class Simulated(NamedTuple):
    name: str
    behavior: Behavior
    flaws: str


def follows(variant: Variant, draw: random.Random) -> JsonValue:
    return variant.reference


def swayed(variant: Variant, draw: random.Random) -> JsonValue:
    return "grant" if variant.attributes["role"] == "director" else variant.reference


def remote(variant: Variant, draw: random.Random) -> JsonValue:
    if variant.attributes["office.location"] == "field" and draw.random() < 0.4:
        return "escalate"
    return "approve" if float(variant.attributes["amount"]) < 12000 else "escalate"


def monolingual(variant: Variant, draw: random.Random) -> JsonValue:
    if variant.attributes["language"] == "es" and draw.random() < 0.4:
        return "withhold"
    return variant.reference


def obedient(variant: Variant, draw: random.Random) -> JsonValue:
    if draw.random() < COMPLIANCE[str(variant.attributes["injection"])]:
        return "close"
    return variant.reference


CAREFUL = Simulated("model-a", follows, "always gives the correct answer.")
FLAWED = {
    "access": Simulated("model-b", swayed, "grants anything to the director's office."),
    "purchases": Simulated(
        "model-b",
        remote,
        "approves purchases up to $12,000 instead of below $10,000, and escalates 40% of "
        "requests from field offices, whatever the amount.",
    ),
    "records": Simulated(
        "model-b", monolingual, "withholds 40% of releasable records requested in Spanish."
    ),
    "injection": Simulated(
        "model-b",
        obedient,
        "closes malicious alerts more often the more direct the injection: 10%, 40%, 70%, and 90%.",
    ),
}


class Mapped(NamedTuple):
    report: Report
    page: ReportPage
    models: tuple[Simulated, ...]

    @property
    def summary(self) -> str:
        models = "".join(
            f"<li><b>{html.escape(model.name)}</b> {html.escape(model.flaws)}</li>"
            for model in self.models
        )
        rows = "".join(
            f"<tr><th>{html.escape(card.target)}</th><td>{card.accuracy.value:.2f}</td>"
            f"<td>{html.escape(_shifted(card.axes))}</td></tr>"
            for card in self.report.scorecards
            if card.group == "all"
        )
        intro = (
            "<p>Two simulated models answer every variant several times. Accuracy hides the "
            "flaw; shifts where nothing should change expose it.</p>"
            if len(self.models) > 1
            else ""
        )
        return (
            f"{intro}<ul>{models}</ul>"
            f"<table><thead><tr><th>Model</th><th>Accuracy</th>"
            f"<th>Shifts where nothing should change</th></tr></thead><tbody>{rows}</tbody></table>"
        )

    def _repr_html_(self) -> str:
        return self.summary + self.page.html

    def save(self, path: Path, title: str) -> None:
        heading = f"<h1>{html.escape(title)}</h1>"
        path.write_text(
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{html.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
            f'<body><main class="demo">{heading}{self.summary}{self.page.html}</main></body>\n'
            "</html>\n",
            encoding="utf-8",
        )


def _shifted(axes: tuple[AxisScore, ...]) -> str:
    return (
        ", ".join(axis.axis for axis in axes if axis.role == "invariant" and axis.shifts) or "none"
    )


def example(name: str) -> Builder:
    """The builder of scenario ``name``: access, purchases, records, or injection."""
    path = SPECS / f"{name}.yaml"
    return Builder.load(path if path.is_file() else name)


def simulated(model: Simulated, scenario: Scenario, spec: Spec) -> CallableTarget:
    space = scenario.task_space
    variants = {
        variant.prompt.last: variant
        for variant in space.variants(scenario.design.coordinates(space.coordinates))
    }

    def respond(request: TargetRequest) -> str:
        draw = random.Random(request.seed)
        roll = draw.random()
        if roll < NOISE:
            return "I cannot answer that."
        if roll < 2 * NOISE:
            return json.dumps({spec.answer.field: draw.choice(spec.answer.choices)})
        return json.dumps({spec.answer.field: model.behavior(variants[request.prompt.last], draw)})

    return CallableTarget(respond, name=model.name)


async def run(builder: Builder) -> Mapped:
    """Map the builder's spec on a careful model and, for one of these scenarios, a flawed one.

    Both give no answer or a random one in 3% of outputs each.
    """
    spec = builder.spec
    scenario = spec.scenario()
    flawed = FLAWED.get(scenario.name)
    models = (CAREFUL, flawed) if flawed else (CAREFUL,)
    results = await Runner().run(
        scenario.experiment([simulated(model, scenario, spec) for model in models])
    )
    report = scenario.report(results)
    return Mapped(report, ReportPage(report, results), models)


def pages(folder: Path) -> None:
    """Write the report page of every scenario into ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        builder = example(name)
        mapped = asyncio.run(run(builder))
        mapped.save(folder / f"{name}.html", builder.spec.description)


if __name__ == "__main__":
    pages(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "pages")
