# Scenarios

A scenario states the expected behavior of a model on one task: the variants it asks, and the correct answer of each. It is fixed, so every model is mapped the same way.

## Where scenarios come from

| Source  | How                                                                                   |
| ------- | ------------------------------------------------------------------------------------- |
| shipped | `modelscape list` names them; `modelscape run pressure` runs one                      |
| spec    | a YAML file: a prompt with slots, what to vary, and the correct answer ([Specs](specs.md)) |
| builder | a notebook widget that writes a spec from one example prompt ([Builder](builder.md)) |
| agent   | a coding agent writes the spec for you to review ([AI agents](agents.md))             |
| Python  | a `Template`, or a task language when the correct answer needs a computation ([Concepts](concepts.md#task-language)) |
| package | another package registers its scenarios by name, as below                             |

## Shipped scenarios

| Scenario       | Question                                                                          | Written as |
| -------------- | --------------------------------------------------------------------------------- | ---------- |
| `conditioning` | Do answers on sensitive topics depend on the language, unlike matched controls?  | spec       |
| `injection`    | Does an analyst triage alerts by the evidence, not by instructions an attacker planted? | spec |
| `pressure`     | Does an assistant open restricted data under pressure or claimed rank?            | spec       |
| `sources`      | Is a source rated by its track record, not by its name?                           | spec       |
| `evidence`     | Does an analyst switch hypotheses when the evidence does?                          | Python     |

The specs are in [`modelscape/scenarios/`](https://github.com/Modelscape/modelscape/tree/main/modelscape/scenarios). Open one in the [builder](builder.md) with `Builder.load("pressure")`. `evidence` is written in Python because its correct answer weighs every report by its reliability, which a spec cannot compute.

`modelscape run` takes a shipped name, a spec file, or a Python module that defines `SCENARIO`. To make your own scenario runnable by name, register it in your package:

```toml
[project.entry-points."modelscape.scenarios"]
refunds = "my_package.refunds:SCENARIO"
```

## Scorecard

Every run gives one scorecard per model:

| Number          | Meaning                                                                  | Ideal |
| --------------- | ------------------------------------------------------------------------ | ----- |
| accuracy        | correct answers at the baseline, with a 95% interval                     | 1     |
| answered        | outputs from which an answer could be read                               | 1     |
| spurious change | answers that move where the correct answer stays, beyond noise           | 0     |
| missed change   | answers that stay where the correct answer moves                         | 0     |
| role            | per axis: **causal** if it should change the answer, else **invariant**  |       |
| shifts          | per axis: where answers change beyond noise                              | only on causal axes |
| threshold       | per causal numeric axis: where the answer flips, beside where it should  | the same point |

On a nominal axis, a shift compares a value with the baseline, such as `role=director`. On an ordinal or numeric axis, it compares neighbors, such as `pressure 4 → 5`. An unreadable answer counts as a wrong one, so read every number with `answered`.

<figure class="diagram">
--8<-- "diagrams/scorecard.svg"
</figure>

## Comparing models

Pass several targets. The first is the reference:

```bash
modelscape run pressure --target openai:<a> --target anthropic:<b>
```

The report then lists where each model differs from the reference beyond the noise of both. The same works for a new release (`--target <old> --target <new>`) or for drift over time: label a target, as in `--target openai:<model>#2026-10`, and run it again later next to a new label. Stored outputs are reused.

To choose between models across several scenarios, save a report per scenario and compare them:

```bash
modelscape compare runs/*.json --require "invariant_shifts==0" --require "answered>=0.95"
```

## Gating CI

`--require` turns a run into a test that exits with status 1 when a requirement is missed:

```bash
modelscape run pressure --target openai:<model> --require "accuracy>=0.95" --require "invariant_shifts==0"
modelscape check pressure.json --require "invariant_shifts==0"
```

Requirements bound `accuracy`, `answered`, `spurious_change`, `missed_change`, `invariant_shifts` (the number of shifts on invariant axes), or `divergences` (where a model differs from the reference). Prefix a case group to check only that group, as in `sensitive:invariant_shifts==0`, and use `--gate-target` to check only some models.

```yaml
- run: pip install "modelscape[openai]"
- run: modelscape run pressure --target openai:<model> --require "invariant_shifts==0"
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## From Python

```python
import asyncio

from modelscape import CallableTarget, Runner
from modelscape.scenarios import load


def always_grant(request):
    return '{"decision": "grant"}'


async def main():
    scenario = load("pressure")
    target = CallableTarget(always_grant, name="always-grant")
    results = await Runner().run(scenario.experiment([target]))
    print(scenario.report(results).summary())


asyncio.run(main())
```

`CallableTarget` wraps any function, so you can map your own application or try modelscape without a model. In a notebook, `await` the run instead of `asyncio.run`, and show `ReportPage(report, results)` to explore it. `modelscape.gate.check(report, requirements)` checks requirements.

## Every prompt

`scenario.prompts()` returns every variant as a pandas DataFrame, with the `pandas` extra:

```python
from modelscape.scenarios import load

prompts = load("pressure").prompts()
prompts[prompts["changed"] == "requester"]
```

| Column      | Holds                                                   |
| ----------- | ------------------------------------------------------- |
| `case`      | the case the variant is made from                       |
| one per axis | the variant's value on that axis                       |
| `changed`   | the axes that differ from the baseline, empty at the baseline |
| `system`    | the system prompt                                       |
| `prompt`    | the user message                                        |
| `reference` | the correct answer                                      |
| `variant`   | the variant's id, as stored with its outputs            |

## Provenance

Every report records the modelscape version, each model's full settings, the model versions the provider reported serving, failures, token use, and when the outputs were made.
