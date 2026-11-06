# FAQ

## The method

### How is this different from a benchmark?

A benchmark tells you how often a model is right. Modelscape tells you what its answers depend on. A model can score almost perfectly and still change its answer with something that should not matter, such as who claims to be asking. See [Concepts](concepts.md).

### How is this different from promptfoo, DeepEval, or Inspect?

Those frameworks score outputs on test cases you write. Modelscape generates the test cases: from one spec it builds every variant, knows the correct answer of each, and so knows which details should move the answer and which must not. It then separates real change from the model's own noise. Use it next to them.

### Is this red-teaming?

No. A red-teaming tool searches for any input that breaks a model. Modelscape measures how one controlled change affects the answer, across many cases. The shipped `pressure` and `injection` scenarios test known pressures, such as claimed authority and planted instructions, and report how often each one works.

### How does it relate to CheckList?

[CheckList](https://aclanthology.org/2020.acl-main.442/) introduced invariance tests, where a change should not move the prediction, and directional tests, where it should. Modelscape applies the same idea to LLMs and adds what they need: repeated sampling, statistics that separate change from noise, and perturbations checked to change one attribute and nothing else.

### Why ask every prompt several times?

A model can give different answers to the same prompt, even at temperature 0 on most hosted APIs. Repeating each prompt measures that noise, so a change is reported only when it is larger than the noise.

### What is a shift?

A change in answers that is larger than that noise. Where the correct answer changes too, a shift is expected. Where it does not, the shift is a flaw.

### Does a shift tell me why the model does it?

No. A shift says where to look, not why. In the report, click a shift to read the prompts and outputs behind it.

### Which answers can it test?

A spec tests decisions: an answer read from a JSON field or a regular expression, out of a fixed set of choices. In Python, difference measures also compare free-text outputs by wording, meaning, or claims. See [Measures](concepts.md#measures).

## Running

### How many calls does a run make?

Variants × repetitions × models. `modelscape describe <spec>` prints the count before anything runs. The [examples](examples/index.md) make 720 to 1,200 calls per model.

### How do I keep the cost down?

Lower `cases` or `repetitions` in the spec while you develop it, and raise them for the final run. Every output is stored in `modelscape.db`, so a rerun asks the model only what it has not answered yet.

### Which temperature does it use?

The provider's default. In Python, every target but Anthropic takes `temperature` and `top_p`. Every setting that affects behavior is recorded in the report.

### Does my data leave my machine?

Only the prompts go to the provider you choose. With [Ollama](providers.md#local-models), nothing leaves the machine. Outputs and reports are local files.

### Can I test my own application instead of a model?

Yes. Anything that takes a prompt and returns an answer can be mapped, such as a prompt chain, a RAG pipeline, or an agent. Wrap it in `CallableTarget`. See [From Python](scenarios.md#from-python).

### Do I need to write Python?

No. A spec is YAML and the CLI runs it. The [builder](builder.md) writes specs in a notebook, and a [coding agent](agents.md) can write them for you.

## Using the results

### How do I compare two models, or two releases?

Pass both as targets. The report lists where they differ beyond the noise of both. See [Comparing models](scenarios.md#comparing-models).

### How do I gate a deployment?

Add `--require "invariant_shifts==0"` to `modelscape run`. It exits with status 1 when a requirement is missed. See [Gating CI](scenarios.md#gating-ci).

### How do I report results in a paper?

Report the scenario's name and version, the number of cases and repetitions, and the scorecard with its intervals. Every report records the modelscape version, each model's settings, the model versions the provider served, and when the outputs were made. Share the spec so others can rerun it; the same `seed` draws the same cases.

### How do I cite modelscape?

Use the [citation file](https://github.com/Modelscape/modelscape/blob/main/CITATION.cff), or *Cite this repository* on GitHub.

### Is it free?

Yes. Modelscape is MIT licensed. You pay only for the model calls your provider charges.
