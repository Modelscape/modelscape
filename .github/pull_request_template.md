## What changes

<!-- One or two sentences: what this pull request does and why. -->

## How it was checked

<!-- Tests added or changed, and anything checked by hand, such as a report page or a figure. -->

## Checklist

- [ ] `uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest` passes
- [ ] `npm --prefix page run check && npm --prefix page test` passes, if `page/` changed
- [ ] Docs and READMEs describe the new behavior
- [ ] A scenario whose results could change has a new `version`
- [ ] No comments in code unless the behavior is not obvious
