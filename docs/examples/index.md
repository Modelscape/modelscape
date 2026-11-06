# Examples

Four scenarios, each mapped on two simulated models. `model-a` gives the correct answer; `model-b` has one planted flaw. Both score about the same accuracy, so accuracy alone cannot tell them apart. The report can.

| Question                                                                             | Spec             |
| ------------------------------------------------------------------------------------ | ---------------- |
| [Is access decided by the classification, not by who asks?](access.md)              | `access.yaml`    |
| [Is a purchase approved at the right threshold, whichever office asks?](purchases.md) | `purchases.yaml` |
| [Is a records request decided by the records, not the language?](records.md)         | `records.yaml`   |
| [Can an attacker steer the model through the data it reads?](injection.md)           | shipped          |

Each example walks through the same four steps: the prompt, what changes, the result, and how to spot the flaw in the report page.

!!! note "Simulated models"
    Both models give no answer or a random one in 3% of outputs, as real models do. Every scenario is made up.

## Reading a report page

1. **Scorecards.** One row per model. Compare *spurious change*: how much answers move where they should not. Near 0 is good.
2. **Axes.** One card per thing the scenario varies. A *causal* axis should move the answer; an *invariant* one should not.
3. **Shifts.** A change beyond the model's own noise. An orange shift sits on an invariant axis: that is the flaw.
4. **Outputs.** Click a dot or a shift to read what the model actually said.

Hover the <span class="ms-i">i</span> icons on the page for help on each part.

## Run them

[`examples/builder.ipynb`](https://github.com/Modelscape/modelscape/blob/main/examples/builder.ipynb) opens each scenario in the [builder](../builder.md) and maps it, offline, in seconds:

```bash
npm --prefix page ci && npm --prefix page run build
uv run --group notebook jupyter lab examples/builder.ipynb
```

The specs are in [`examples/specs/`](https://github.com/Modelscape/modelscape/tree/main/examples/specs). Run one on a real model like any spec:

```bash
modelscape run examples/specs/purchases.yaml --target openai:<model>
```
