"""Write a release's files: uv run --isolated --no-project --with modelscape==X python write.py X"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from modelscape import CallableTarget, Runner, TargetRequest, scenarios
from modelscape.storage import SQLiteStore

STEADY = "callable:steady"
SWAYED = "callable:swayed"


def answer(request: TargetRequest, swayed: bool) -> str:
    text = request.prompt.messages[-1].content
    grant = "OFFICIAL" in text or (swayed and "director" in text)
    return '{"decision": "grant"}' if grant else '{"decision": "deny"}'


async def write(folder: Path) -> None:
    scenario = scenarios.load(str(folder / "spec.yaml"))
    targets = [
        CallableTarget(lambda request: answer(request, False), name=STEADY),
        CallableTarget(lambda request: answer(request, True), name=SWAYED),
    ]
    with SQLiteStore(folder / "store.db") as store:
        results = await Runner(store=store).run(scenario.experiment(targets))
    scenario.report(results).save(folder / "report.json")


if __name__ == "__main__":
    asyncio.run(write(Path(__file__).parent / sys.argv[1]))
