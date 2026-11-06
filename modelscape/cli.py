"""The modelscape command: list, describe, review, and run scenarios; check, compare, view reports.

``schema`` and ``skill`` serve coding agents that write specs.

modelscape run pressure --target openai:<model> --require "invariant_shifts==0"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import webbrowser
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path
from typing import cast

from modelscape import scenarios
from modelscape.core.errors import ReportError, RequirementError, ScenarioError, StoreError
from modelscape.execution import ExecutionConfig, Progress, Runner
from modelscape.gate import Requirement, check
from modelscape.page import Page, ReportPage, ScenarioPage
from modelscape.report import Report
from modelscape.scenario import Scenario
from modelscape.spec import Spec
from modelscape.storage import SQLiteStore
from modelscape.targets import Target
from modelscape.targets.protocols import Closable

SKILL = Path(__file__).parent / "skills" / "modelscape"
DESCRIPTION = "Map large language models with controlled, repeated behavioral tests."
SCENARIO_HELP = "a registered name, a YAML spec, or a module, file, or folder defining SCENARIO"
TARGET_HELP = "provider:model[#label], repeatable; the first is the reference"
REQUIRE_HELP = (
    "[group:]quantity<op>number, such as accuracy>=0.9; exit 1 when missed. Quantities: "
    "accuracy, answered, spurious_change, missed_change, invariant_shifts, divergences"
)

COLUMNS = (
    "scenario",
    "group",
    "target",
    "accuracy",
    "answered",
    "spurious",
    "missed",
    "invariant shifts",
)

PROVIDERS = {
    "anthropic": "AnthropicTarget",
    "openai": "OpenAITarget",
    "azure": "AzureOpenAITarget",
    "bedrock": "BedrockTarget",
    "google": "GoogleGenAITarget",
    "ollama": "OllamaTarget",
}


def load(reference: str) -> Scenario:
    try:
        return scenarios.load(reference)
    except ScenarioError as error:
        raise SystemExit(str(error)) from error


def requirements(specs: Sequence[str]) -> list[Requirement]:
    try:
        return [Requirement.parse(spec) for spec in specs]
    except RequirementError as error:
        raise SystemExit(str(error)) from error


def gate(
    report: Report, required: Sequence[Requirement], targets: Sequence[str] | None = None
) -> None:
    if not required:
        return
    try:
        failures = check(report, required, targets or None)
    except RequirementError as error:
        raise SystemExit(str(error)) from error
    if failures:
        print("\nRequirements not met:", *(f"  {line}" for line in failures), sep="\n")
        raise SystemExit(1)
    print(f"\nAll requirements met: {', '.join(map(str, required))}")


def listing() -> str:
    names = list(scenarios.available())
    width = max(map(len, names), default=0) + 2
    return "\n".join(f"{name:<{width}}{_listed(name)}" for name in names)


def _listed(name: str) -> str:
    try:
        scenario = scenarios.load(name)
    except Exception as error:
        return f"cannot be loaded: {type(error).__name__}: {error}"
    return f"{scenario.version:<4}{scenario.description}"


def comparison(reports: Sequence[Report], required: Sequence[Requirement]) -> str:
    """Every scorecard of every report side by side, and the targets that meet ``required``."""
    rows = [
        (
            f"{report.scenario.name} {report.scenario.version}",
            card.group,
            card.target,
            _number(card.accuracy.value),
            _number(card.answered),
            _number(card.spurious_change),
            _number(card.missed_change),
            str(card.invariant_shifts),
        )
        for report in reports
        for card in report.scorecards
    ]
    widths = [max(len(row[column]) for row in [COLUMNS, *rows]) for column in range(len(COLUMNS))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in [COLUMNS, *rows]
    ]
    if not required:
        return "\n".join(lines)
    groups = {card.group for report in reports for card in report.scorecards}
    unknown = sorted({item.group for item in required if item.group is not None} - groups)
    if unknown:
        raise SystemExit(f"No report has groups {', '.join(unknown)}.")
    missed: dict[str, list[str]] = {}
    for report in reports:
        present = {card.group for card in report.scorecards}
        applicable = [item for item in required if item.group is None or item.group in present]
        for name in dict.fromkeys(card.target for card in report.scorecards):
            missed.setdefault(name, []).extend(
                f"{report.scenario.name} {line}" for line in check(report, applicable, [name])
            )
    meeting = [name for name, found in missed.items() if not found]
    lines.append(f"\nMeets {', '.join(map(str, required))}: {', '.join(meeting) or 'no target'}")
    lines.extend(f"  {line}" for found in missed.values() for line in found)
    return "\n".join(lines)


def publish(page: Page, path: str | Path, browse: bool) -> None:
    written = page.save(path)
    print(written)
    if browse:
        webbrowser.open_new_tab(written.resolve().as_uri())


def install(folder: str | Path) -> Path:
    """Copy the agent skill into ``folder``, such as ``.claude/skills``, and return its path."""
    destination = Path(folder) / SKILL.name
    shutil.copytree(SKILL, destination, dirs_exist_ok=True)
    return destination


def target(spec: str, max_tokens: int) -> Target:
    provider, _, rest = spec.partition(":")
    model, _, label = rest.partition("#")
    if provider not in PROVIDERS or not model:
        raise SystemExit(
            f"Targets look like provider:model[#label], with a provider in {sorted(PROVIDERS)}."
        )
    name = f"{provider}:{model}" + (f"#{label}" if label else "")
    try:
        factory = cast(
            Callable[..., Target],
            getattr(import_module("modelscape.targets"), PROVIDERS[provider]),
        )
        return factory(model, max_tokens=max_tokens, name=name)
    except Exception as error:
        raise SystemExit(f"Cannot create target {spec}: {error}") from error


async def run(
    scenario: Scenario,
    targets: Sequence[Target],
    store: str,
    execution: ExecutionConfig | None = None,
) -> Report:
    try:
        with SQLiteStore(store) as records:
            results = await Runner(store=records, on_progress=_progress).run(
                scenario.experiment(targets, execution)
            )
    finally:
        await asyncio.gather(*(item.aclose() for item in targets if isinstance(item, Closable)))
    print(file=sys.stderr)
    return scenario.report(results)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the modelscape command."""
    parser = argparse.ArgumentParser(prog="modelscape", description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list registered scenarios")
    describing = commands.add_parser("describe", help="check a scenario and count its calls")
    describing.add_argument("scenario", help=SCENARIO_HELP)
    describing.add_argument(
        "--prompts", action="store_true", help="also print every variant of the first case"
    )
    reviewing = commands.add_parser(
        "review", help="write every variant and its correct answer as one HTML page"
    )
    reviewing.add_argument("scenario", help=SCENARIO_HELP)
    reviewing.add_argument("--html", help="where to write the page; next to the spec by default")
    commands.add_parser("schema", help="print the JSON Schema of a spec")
    skill = commands.add_parser("skill", help="print the skill that teaches agents to write specs")
    skill.add_argument(
        "--install",
        metavar="FOLDER",
        help="copy the skill into FOLDER/modelscape, such as .claude/skills or .agents/skills",
    )
    running = commands.add_parser("run", help="map targets with a scenario")
    running.add_argument("scenario", help=SCENARIO_HELP)
    running.add_argument("--target", action="append", required=True, help=TARGET_HELP)
    running.add_argument("--store", default="modelscape.db", help="where outputs are kept")
    running.add_argument("--report", help="write the report to this JSON file")
    running.add_argument("--max-tokens", type=_positive, default=1024)
    running.add_argument("--concurrency", type=_positive, default=8)
    checking = commands.add_parser("check", help="check a saved report against requirements")
    checking.add_argument("report", help="a report JSON file")
    comparing = commands.add_parser(
        "compare", help="compare targets across reports and select those meeting requirements"
    )
    comparing.add_argument("reports", nargs="+", help="report JSON files")
    comparing.add_argument(
        "--require",
        action="append",
        default=[],
        help="[group:]quantity<op>number; name the targets that meet every requirement",
    )
    viewing = commands.add_parser("view", help="write a report as one shareable HTML page")
    viewing.add_argument("report", help="a report JSON file")
    viewing.add_argument("--store", help="the store the run wrote, to show the outputs behind it")
    viewing.add_argument("--html", help="where to write the page; next to the report by default")
    for command in (reviewing, viewing):
        command.add_argument("--no-open", action="store_true", help="do not open it in a browser")
    for command, required in ((running, False), (checking, True)):
        command.add_argument(
            "--require", action="append", required=required, default=[], help=REQUIRE_HELP
        )
        command.add_argument(
            "--gate-target", action="append", default=[], help="check only these targets"
        )
    arguments = parser.parse_args(argv)
    try:
        _command(arguments)
    except (OSError, ReportError, StoreError) as error:
        raise SystemExit(str(error)) from error


def _command(arguments: argparse.Namespace) -> None:
    if arguments.command == "list":
        print(listing())
        return
    if arguments.command == "schema":
        print(json.dumps(Spec.model_json_schema(), indent=2))
        return
    if arguments.command == "skill":
        if arguments.install:
            print(install(arguments.install))
        else:
            print((SKILL / "SKILL.md").read_text(encoding="utf-8"), end="")
        return
    if arguments.command == "compare":
        loaded = [Report.load(path) for path in arguments.reports]
        print(comparison(loaded, requirements(arguments.require)))
        return
    if arguments.command == "view":
        page = ReportPage(arguments.report, arguments.store)
        publish(
            page,
            arguments.html or Path(arguments.report).with_suffix(".html"),
            not arguments.no_open,
        )
        return
    if arguments.command == "check":
        report = Report.load(arguments.report)
        print(report.summary())
        gate(report, requirements(arguments.require), arguments.gate_target)
        return
    scenario = load(arguments.scenario)
    if arguments.command == "review":
        found = Path(arguments.scenario)
        beside = found.with_suffix(".html") if found.exists() else Path(f"{scenario.name}.html")
        publish(ScenarioPage(scenario), arguments.html or beside, not arguments.no_open)
        return
    if arguments.command == "describe":
        print(scenario.describe())
        if arguments.prompts:
            print(f"\n{scenario.example()}")
        return
    required = requirements(arguments.require)
    report = asyncio.run(
        run(
            scenario,
            [target(spec, arguments.max_tokens) for spec in arguments.target],
            arguments.store,
            ExecutionConfig(concurrency=arguments.concurrency),
        )
    )
    print(report.summary())
    if arguments.report:
        report.save(arguments.report)
    gate(report, required, arguments.gate_target)


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected a whole number above 0, got {text!r}")
    return value


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _progress(progress: Progress) -> None:
    print(
        f"\r{progress.completed}/{progress.total} observations, {progress.reused} reused, "
        f"{progress.failed} failed",
        end="",
        file=sys.stderr,
    )
