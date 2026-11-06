from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from modelscape import scenarios
from modelscape.cli import SKILL, main
from modelscape.core.files import parse_yaml

ROOT = Path(__file__).resolve().parent.parent


def frontmatter(text: str) -> dict[str, str]:
    _, header, _ = text.split("---\n", 2)
    return cast(dict[str, str], parse_yaml(header))


def test_the_skill_follows_the_agent_skills_format() -> None:
    header = frontmatter((SKILL / "SKILL.md").read_text(encoding="utf-8"))
    assert set(header) == {"name", "description"}
    assert header["name"] == SKILL.name == "modelscape"
    assert 0 < len(header["description"]) <= 1024


def test_the_marketplace_serves_the_packaged_skill() -> None:
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    [plugin] = marketplace["plugins"]
    assert (ROOT / plugin["source"] / "skills" / SKILL.name).resolve() == SKILL.resolve()


def test_skill_command_prints_the_skill(capsys: pytest.CaptureFixture[str]) -> None:
    main(["skill"])
    assert capsys.readouterr().out == (SKILL / "SKILL.md").read_text(encoding="utf-8")


def test_skill_command_installs_the_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["skill", "--install", str(tmp_path / ".agents" / "skills")])
    installed = tmp_path / ".agents" / "skills" / "modelscape"
    assert capsys.readouterr().out.strip() == str(installed)
    assert (installed / "SKILL.md").read_bytes() == (SKILL / "SKILL.md").read_bytes()
    main(["skill", "--install", str(tmp_path / ".agents" / "skills")])
    assert (installed / "SKILL.md").is_file()


def test_schema_command_prints_the_spec_schema(capsys: pytest.CaptureFixture[str]) -> None:
    main(["schema"])
    schema = json.loads(capsys.readouterr().out)
    assert set(schema["required"]) == {"name", "prompt", "slots", "vary", "answer"}


def test_describe_prints_every_variant_of_the_first_case(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["describe", "pressure", "--prompts"])
    out = capsys.readouterr().out
    scenario = scenarios.load("pressure")
    assert out == f"{scenario.describe()}\n\n{scenario.example()}\n"


def test_an_example_labels_each_variant_by_what_it_changes() -> None:
    example = scenarios.load("pressure").example()
    labels = [line for line in example.splitlines() if "  correct: " in line]
    assert labels[0] == "baseline  correct: escalate"
    assert "pressure=5  correct: escalate" in labels
    assert "dataset.restricted=False  correct: grant" in labels
    assert example.startswith("case ")
    assert "\nsystem\n  You handle data-access requests" in example
