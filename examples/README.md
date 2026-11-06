# Examples

`builder.ipynb` is a demo: four scenarios, each opened in the builder and mapped on a careful and a flawed simulated model.

```bash
npm --prefix page ci && npm --prefix page run build
uv run --group notebook jupyter lab examples/builder.ipynb
```

`specs/` holds the scenarios, and `demo.py` the flawed behaviors planted in the simulated models of `modelscape.demo`. `uv run python examples/demo.py` writes each scenario's report page into `pages/`.
