from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from modelscape import CallableTarget, Report, Runner, TargetRequest, scenarios
from modelscape.cli import main
from modelscape.core import ReportError, StoreError
from modelscape.report import FORMAT as REPORT_FORMAT
from modelscape.storage import SQLiteStore
from modelscape.storage.sqlite import FORMAT as STORE_FORMAT
from tests.compat.write import STEADY, SWAYED

RELEASES = sorted(
    path for path in (Path(__file__).parent / "compat").iterdir() if (path / "spec.yaml").is_file()
)


@pytest.fixture(params=RELEASES, ids=lambda path: path.name)
def release(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    copy = tmp_path / request.param.name
    shutil.copytree(request.param, copy)
    return copy


def test_released_reports_load_and_check(release: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = Report.load(release / "report.json")
    assert report.provenance.modelscape == release.name
    assert Report.model_validate_json(report.model_dump_json()) == report
    main(["check", str(release / "report.json"), "--require", "answered>=1"])
    main(["compare", str(release / "report.json")])
    assert "callable:swayed" in capsys.readouterr().out


async def test_released_stores_are_reused_on_a_rerun(release: Path) -> None:
    calls: list[TargetRequest] = []

    def call(request: TargetRequest) -> str:
        calls.append(request)
        return '{"decision": "deny"}'

    scenario = scenarios.load(str(release / "spec.yaml"))
    targets = [CallableTarget(call, name=STEADY), CallableTarget(call, name=SWAYED)]
    with SQLiteStore(release / "store.db") as store:
        results = await Runner(store=store).run(scenario.experiment(targets))
    released = Report.load(release / "report.json")
    rerun = scenario.report(results)
    assert calls == []
    assert [item.observations for item in rerun.provenance.targets] == [
        item.observations for item in released.provenance.targets
    ]


def test_released_stores_show_their_outputs(release: Path) -> None:
    page = release / "page.html"
    report, store = release / "report.json", release / "store.db"
    main(["view", str(report), "--store", str(store), "--html", str(page), "--no-open"])
    assert '"observations":[{' in page.read_text(encoding="utf-8")


def test_reports_of_a_newer_format_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(f'{{"format": {REPORT_FORMAT + 1}}}', encoding="utf-8")
    with pytest.raises(ReportError, match="Upgrade modelscape"):
        Report.load(path)
    with pytest.raises(SystemExit, match="Upgrade modelscape"):
        main(["check", str(path), "--require", "answered>=0"])


def test_stores_record_their_format_and_refuse_a_newer_one(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    SQLiteStore(path).close()
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == STORE_FORMAT
    connection.execute(f"PRAGMA user_version = {STORE_FORMAT + 1}")
    connection.close()
    with pytest.raises(StoreError, match="Upgrade modelscape"):
        SQLiteStore(path)
    with pytest.raises(SystemExit, match="Upgrade modelscape"):
        main(["run", "pressure", "--target", "ollama:qwen-test", "--store", str(path)])
