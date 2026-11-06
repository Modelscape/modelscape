# Modelscape

Modelscape is a Python 3.11+ library and CLI for controlled behavioral mapping of large language models. It defines typed tasks and checked perturbations, runs scenarios against model providers, analyzes changes beyond run-to-run noise, and produces reports and visualizations.

## Development guidance

- Keep the code free of comments unless a comment is essential for understanding non-obvious behavior.
- After making changes, check whether the related documentation or README also needs to be updated.
- Ensure all CI workflows pass.
- Ensure the test suite passes.
- Never credit Claude in commits or pull requests: no `Co-Authored-By: Claude` trailer and no "Generated with Claude Code" line.

## Setup

- Manage dependencies and commands with `uv`.
- Install the development environment with `uv sync --all-groups`.
- Run tests with `uv run pytest`.
- Run linting with `uv run ruff check .`.
- Run the CLI with `uv run modelscape`.
