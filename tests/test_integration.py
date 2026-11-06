from __future__ import annotations

import os
from pathlib import Path

import pytest

from modelscape import Report
from modelscape.cli import main, target
from modelscape.core import Prompt, TargetRequest
from modelscape.targets.protocols import Closable

pytestmark = pytest.mark.integration

REQUEST = TargetRequest(
    prompt=Prompt.of("What is 2 + 2? Answer with one digit."), repetition=0, seed=1
)
PROVIDERS = {
    "MODELSCAPE_ANTHROPIC_MODEL": "anthropic",
    "MODELSCAPE_AZURE_OPENAI_MODEL": "azure",
    "MODELSCAPE_BEDROCK_MODEL": "bedrock",
    "MODELSCAPE_GOOGLE_MODEL": "google",
    "MODELSCAPE_OLLAMA_MODEL": "ollama",
    "MODELSCAPE_OPENAI_MODEL": "openai",
}
SPEC = """\
name: live
description: Does the answer follow the number, not the wording?
system: 'Reply with only a JSON object: {"answer": "yes" or "no"}.'
prompt: '{tone}Is {number} greater than 10?'
slots:
  tone: {plain: '', polite: 'Please answer carefully. '}
  number:
  - {label: three, text: '3', larger: false}
  - {label: forty, text: '40', larger: true}
vary:
  tone: nominal
  number.larger: nominal
answer:
  field: answer
  choices: [yes, no]
  correct:
    number.larger: {true: yes, false: no}
cases: 1
repetitions: 2
"""


def live(variable: str) -> str:
    model = os.environ.get(variable)
    if not model:
        pytest.skip(f"set {variable} and the provider's credentials to run this test")
    return f"{PROVIDERS[variable]}:{model}"


@pytest.mark.parametrize("variable", sorted(PROVIDERS))
async def test_live_target_answers(variable: str) -> None:
    model = target(live(variable), max_tokens=512)
    try:
        output = await model.invoke(REQUEST)
    finally:
        if isinstance(model, Closable):
            await model.aclose()
    assert "4" in output.as_text()
    assert output.usage is not None
    assert output.usage.output_tokens


@pytest.mark.parametrize("variable", sorted(PROVIDERS))
def test_live_target_is_mapped_checked_and_viewed(variable: str, tmp_path: Path) -> None:
    spec, store, report, page = (
        tmp_path / name for name in ("live.yaml", "live.db", "r.json", "r.html")
    )
    spec.write_text(SPEC, encoding="utf-8")
    name = live(variable)
    main(["run", str(spec), "--target", name, "--store", str(store), "--report", str(report)])
    main(["check", str(report), "--require", "answered>=0.5"])
    main(["view", str(report), "--store", str(store), "--html", str(page), "--no-open"])
    (served,) = Report.load(report).provenance.targets
    assert (served.identity.name, served.failed) == (name, 0)
    assert served.observations > 0
    assert '"observations":[{' in page.read_text(encoding="utf-8")
