"""Run a scenario on targets in one call, and keep the report with the results behind it."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property

from modelscape import scenarios
from modelscape.analysis import Results
from modelscape.execution import ExecutionConfig, ProgressCallback, Runner
from modelscape.page import ReportPage
from modelscape.report import Report
from modelscape.scenario import Scenario
from modelscape.storage import SQLiteStore, Store
from modelscape.targets import Target


@dataclass(frozen=True, eq=False)
class Run:
    """A finished run: the scenario, its results, and their report.

    In a notebook it shows as its report page.
    """

    scenario: Scenario
    results: Results
    report: Report

    @cached_property
    def page(self) -> ReportPage:
        """The report as one HTML page, with the outputs behind every number."""
        return ReportPage(self.report, self.results)

    def _repr_html_(self) -> str:
        return self.page.html


async def run(
    scenario: Scenario | str | os.PathLike[str],
    targets: Target | Iterable[Target],
    *,
    store: Store | str | os.PathLike[str] | None = None,
    execution: ExecutionConfig | None = None,
    on_progress: ProgressCallback | None = None,
) -> Run:
    """Map ``targets`` with ``scenario``: a ``Scenario``, a YAML spec, or a registered name.

    ``store`` keeps every output, so a rerun reuses them: a ``Store``, or the path of a SQLite
    file. Without one, outputs are kept in memory.
    """
    found = scenario if isinstance(scenario, Scenario) else scenarios.load(os.fspath(scenario))
    if isinstance(targets, str):
        raise TypeError(f"Pass target objects, such as OpenAITarget, not the text {targets!r}.")
    listed = list(targets) if isinstance(targets, Iterable) else [targets]
    experiment = found.experiment(listed, execution)
    if isinstance(store, str | os.PathLike):
        with SQLiteStore(store) as opened:
            results = await Runner(store=opened, on_progress=on_progress).run(experiment)
    else:
        results = await Runner(store=store, on_progress=on_progress).run(experiment)
    return Run(scenario=found, results=results, report=found.report(results))
