# Contributing to Modelscape

Thank you for contributing. Please open an issue before substantial changes so the approach can be discussed.

## Development setup

Modelscape uses Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 20+ for the report page:

```bash
npm --prefix page ci
npm --prefix page run build
uv sync --locked --all-extras --all-groups
```

Formatting is defined by [`.editorconfig`](.editorconfig), Ruff for Python, and
Prettier and ESLint for the report page. Run the formatters locally when making
changes:

```bash
uv run ruff format .
(cd page && npm exec prettier -- --write .)
```

Continuous integration checks formatting, linting, types, and tests on every
pull request. A pull request cannot merge until those checks pass.

Run the checks before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -n auto --cov
npm --prefix page run check
npm --prefix page test
```

Tests are offline by default, treat warnings as errors, and must keep branch coverage at or above 95%.

## Tests

| Layer | Where | When |
| --- | --- | --- |
| Unit, property, and architecture tests | `tests/` | every pull request, on Python 3.11 to 3.14 |
| Lowest supported dependency versions | `lowest` job in CI | every pull request |
| Reports and stores written by earlier releases | `tests/compat/` | every pull request |
| End to end: the built wheel runs, checks, and views a local Ollama model | `package` job in CI | every pull request |
| Latest dependency versions and live provider APIs | `weekly.yml` | every Monday |

Live tests call real models and are skipped unless a model is set, such as `MODELSCAPE_OPENAI_MODEL` with its credentials or `MODELSCAPE_OLLAMA_MODEL=qwen2.5:0.5b` with Ollama running. Run them with `uv run pytest -m integration`. The weekly run reads model names from repository variables and keys from repository secrets.

Raise a dependency's lower bound when the code needs a newer version; the `lowest` job tests the bounds as declared.

`tests/compat/<version>/` holds a report and a store written by that release; never edit them. When a release changes how reports or stores are written, raise `FORMAT` in `report.py` or `storage/sqlite.py`, keep older files readable, and add the release's files:

```bash
mkdir tests/compat/<version> && cp tests/compat/0.4.0/spec.yaml tests/compat/<version>/
uv run --isolated --no-project --with modelscape==<version> python tests/compat/write.py <version>
```

## Pull requests

- Keep changes focused and add or update tests.
- Update relevant documentation and READMEs.
- Add a new scenario `version` when its results can change.
- Do not include API keys, private prompts, or sensitive model outputs.
- Describe what changed and how it was checked.
