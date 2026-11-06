# FAQ

## How is this different from a benchmark?

A benchmark tells you how often a model is right. Modelscape tells you what its answers depend on. A model can score almost perfectly and still change its answer with something that should not matter, such as who claims to be asking. See [Concepts](concepts.md).

## Why ask every prompt several times?

A model can give different answers to the same prompt. Repeating each prompt measures that noise, so a change is reported only when it is larger than the noise.

## What is a shift?

A change in answers that is larger than that noise. Where the correct answer changes too, a shift is expected. Where it does not, the shift is a flaw.

## Does a shift tell me why the model does it?

No. A shift says where to look, not why. In the report, click a shift to read the prompts and outputs behind it.

## Can I test my own application instead of a model?

Yes. Anything that takes a prompt and returns an answer can be mapped, such as a prompt chain or an agent. See [Scenarios](scenarios.md#from-python).
