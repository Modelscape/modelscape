# Concepts

<figure class="diagram">
--8<-- "diagrams/pipeline.svg"
</figure>

## Why

Benchmarks rank models by a matrix of scores, *Y* ∈ ℝ<sup>*n*×*m*</sup>, for *n* models on *m* benchmarks. These scores now carry regulatory weight: the EU AI Act requires evaluations of general-purpose models with systemic risk, and declared accuracy and robustness for high-risk systems. Yet a score is a weak guide to behavior. A model's accuracy can move by tens of points with the formatting of the prompt alone ([Sclar et al., 2024](https://arxiv.org/abs/2310.11324)), and its answers vary between runs of the same prompt ([Miller, 2024](https://arxiv.org/abs/2411.00640)). Modelscape measures what a model's answers depend on, instead of how often they are right.

It builds on behavioral testing. [CheckList](https://aclanthology.org/2020.acl-main.442/) (Ribeiro et al., 2020) tests NLP models with invariance tests, where a change should not move the prediction, and directional tests, where it should. Modelscape adds what LLMs need: the expected behavior of every variant, stated as its correct answer; repeated sampling, so change is measured against the model's own noise; and perturbations checked to change one attribute and nothing else.

## Expected and observed behavior

Modelscape holds two representations of behavior over the same task space, and compares them.

| Representation    | What it holds                                                          | Object                                  |
| ----------------- | ---------------------------------------------------------------------- | --------------------------------------- |
| task              | typed fields and the attributes that can vary                          | `Task`, `Template`                      |
| task space        | seed cases, the axes that vary them, and the prompt of each task       | `TaskSpace`, `Axis`                     |
| expected behavior | the correct answer of every variant, and so which axes should matter   | `reference()`, a spec's `answer.correct` |
| variant           | one task at one point, its prompt, its correct answer, and its steps   | `Variant`                               |
| observed behavior | every output at every variant, repeated, with its measurements         | `Results`                               |
| comparison        | shifts beyond noise, set against the expected behavior                 | `Scorecard`, `BehaviorProfile`, `Divergence` |

A [scenario](scenarios.md) fixes the first four, so every model is mapped the same way. A run produces the observed behavior. The analysis compares the two.

## Scenario: the expected behavior

### Task language

A [spec](specs.md) is the simplest task language: its slots are the fields. When the correct answer depends on more structure, such as a list of reports weighed by their reliability, write the task language in Python:

| Object          | Role                                                                    |
| --------------- | ----------------------------------------------------------------------- |
| `Task` subclass | the valid tasks, as typed fields, such as $L$                           |
| `@attribute`    | a property of a task, $\pi_m : L \to V_m$, that an axis can vary        |
| `reference()`   | the correct answer, $G(q)$, computed from the task                      |
| `@perturbation` | a step $\rho_m(q, v)$ that sets one attribute to value $v$              |
| `@realizer`     | the prompt $r(q)$ the model reads                                       |

A perturbation is accepted only if it sets its attribute and changes no other, except those it declares `free=[...]`. The shipped `evidence` scenario is written this way.

<figure class="diagram">
--8<-- "diagrams/perturbation.svg"
</figure>

### Task space

An `Axis` names an attribute, its values, and its [scale](specs.md#scales); the first value is the baseline. A `TaskSpace` builds the variant of any case at any point by checked steps. The `Sweep` design varies one axis at a time around the baseline, and `Grid` covers every combination. Only `Grid` shows how axes interact.

<figure class="diagram">
--8<-- "diagrams/designs.svg"
</figure>

### Roles

The correct answers decide the role of every axis. An axis is **causal** if changing it alone changes the correct answer of some case, and **invariant** otherwise. You never label an axis; the role follows from `reference()`.

## Run: the observed behavior

A model receives only the prompt of each variant, never its task, point, or correct answer. Every variant is asked `repetitions` times, and the repetitions measure the model's own noise. A store keeps every output with the variant that produced it, so a rerun reuses it.

## Analysis: the comparison

### Measures

A **point metric** scores one response, usually against the correct answer. A **difference measure** compares two responses: their answer, their wording (`TokenJaccardDistance`, `NormalizedEditDistance`), their meaning (`EmbeddingCosineDistance`), or their claims (`GraphDistance`). Pass extra measures to a scenario as `measures=[...]`.

### Shifts

Every comparison of two conditions is made within each case, then averaged over cases:

- **between**: how much responses differ across the two conditions;
- **within**: how much repeated responses differ in one condition, the model's noise;
- **excess**: between minus within, with an interval that resamples cases and repetitions;
- **p-value**: a permutation test, corrected for the number of steps tested.

A shift is a step with a significant, positive excess. On a nominal axis, each value is compared with the baseline; on an ordinal or numeric axis, each value with the next. A shift on a causal axis is expected. A shift on an invariant axis is **spurious change**; no shift where the correct answer moves is **missed change**.

<figure class="diagram">
--8<-- "diagrams/noise.svg"
</figure>

| Call                                  | Returns                                                       |
| ------------------------------------- | ------------------------------------------------------------- |
| `results.scorecard(metric, measure)`  | the [scorecard](scenarios.md#scorecard)                       |
| `results.profile(axis, measure)`      | every tested step along one axis, and where the answer shifts |
| `results.divergence(measure, a, b)`   | where two models differ beyond the noise of both              |
| `results.sensitivity(measure)`        | the axes, ranked by their largest change                      |
| `results.agreement()`                 | whether the measures find the same shifts                     |
| `results.trace(item)`                 | the prompts and outputs behind any number                     |

A shift says where to look, not why the model does it.

## Validity

| A finding could come from | Modelscape checks                                               |
| ------------------------- | --------------------------------------------------------------- |
| noise                     | every variant is asked repeatedly; only change beyond it counts |
| the choice of measure     | `results.agreement()` compares measures on the same steps       |
| a flawed perturbation     | every step must change only its own attribute                   |
