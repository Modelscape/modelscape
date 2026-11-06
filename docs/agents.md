# AI agents

A coding agent can write specs for you. It writes the YAML, checks it with `modelscape describe`, and hands it to you to review as one HTML page. Once you agree, it runs the spec and summarises the report.

## Install the skill

The skill teaches an agent the spec format, the workflow, and what makes a good test.

| Agent                                                  | Install                                                     |
| ------------------------------------------------------ | ----------------------------------------------------------- |
| Claude Code                                            | `/plugin marketplace add Modelscape/modelscape`, then `/plugin install modelscape@modelscape` |
| Codex, Cursor, GitHub Copilot, Gemini CLI, and others  | `npx skills add Modelscape/modelscape`                    |
| any agent, from the installed package                  | `modelscape skill --install .agents/skills`                 |

`--install` copies the skill into a folder your agent reads, such as `.claude/skills` for Claude Code, `.cursor/skills` for Cursor, or `.agents/skills` for Codex. An agent without skills can still use it: ask it to run `modelscape skill` and follow it.

## Use it

Ask for the test you want:

> Test whether our access assistant can be talked into releasing SECRET data.

The agent then:

1. asks what should decide the answer and what must not, if you have not said;
2. writes `access.yaml` and checks it with `modelscape describe access.yaml --prompts`;
3. writes `access.html` with `modelscape review access.yaml`, and asks you to review the correct answers;
4. runs it on the model you name, and leads its summary with the shifts that should not happen.

Review the correct answers before anything runs: a test is only as good as they are. The page shows every axis with its role, and every variant of every case with its correct answer and the words it changes. Ask the agent for a change, and it edits the YAML and writes the page again.

You need no Python environment. With [uv](https://docs.astral.sh/uv/), the agent runs modelscape without installing it:

```bash
uvx modelscape review access.yaml
```

To edit the spec yourself in a notebook, open it in the [builder](builder.md) with `Builder.load("access.yaml")`.

## Commands for agents

| Command                                  | Does                                                          |
| ---------------------------------------- | ------------------------------------------------------------- |
| `modelscape skill`                       | prints the skill                                              |
| `modelscape skill --install <folder>`    | copies the skill into `<folder>/modelscape`                   |
| `modelscape schema`                      | prints the JSON Schema of a spec                              |
| `modelscape describe <spec> --prompts`   | checks a spec, and prints every variant of its first case with its correct answer |
| `modelscape review <spec>`               | writes every variant of every case with its correct answer as one HTML page |
