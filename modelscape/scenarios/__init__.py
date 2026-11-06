"""The scenarios that ship with modelscape, and any scenario another package registers.

A scenario is a YAML spec, or a Python module or folder defining ``SCENARIO``. A package
registers its scenarios under the ``modelscape.scenarios`` entry point group, after which
``modelscape run <name>`` finds them by name:

    [project.entry-points."modelscape.scenarios"]
    refunds = "my_package.refunds:SCENARIO"
"""

from __future__ import annotations

import sys
from importlib import import_module
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from modelscape.core.errors import ModelscapeError, ScenarioError
from modelscape.scenario import Scenario
from modelscape.spec import Spec

GROUP = "modelscape.scenarios"
FOLDER = Path(__file__).parent
SPECS = (".yaml", ".yml")


def available() -> dict[str, str]:
    """Every registered scenario name, with the spec or object it points to."""
    found = {path.stem: path.relative_to(FOLDER.parent.parent).as_posix() for path in _shipped()}
    found |= {name: entry.value for name, entry in _registered().items()}
    return dict(sorted(found.items()))


def load(reference: str) -> Scenario:
    """A scenario by registered name, by YAML spec, or by module or folder defining SCENARIO.

    Paths and modules are resolved from the current directory.
    """
    if reference.endswith(SPECS):
        return _specified(Path(reference))
    shipped = {path.stem: path for path in _shipped()}
    if reference in shipped:
        return _specified(shipped[reference])
    registered = _registered()
    found = registered[reference].load() if reference in registered else _imported(reference)
    if not isinstance(found, Scenario):
        raise ScenarioError(f"{reference} does not define SCENARIO = Scenario(...).")
    return found


def spec(name: str) -> Path:
    """The YAML file of shipped scenario ``name``."""
    shipped = {path.stem: path for path in _shipped()}
    if name not in shipped:
        python = sorted(path.parent.name for path in FOLDER.glob("*/__init__.py"))
        kind = "is written in Python" if name in python else "is not a shipped scenario"
        raise ScenarioError(f"{name} {kind}; the shipped specs are {', '.join(shipped)}.")
    return shipped[name]


def _shipped() -> list[Path]:
    return sorted(path for suffix in SPECS for path in FOLDER.glob(f"*/*{suffix}"))


def _registered() -> dict[str, EntryPoint]:
    return {entry.name: entry for entry in entry_points(group=GROUP)}


def _specified(path: Path) -> Scenario:
    if not path.is_file():
        raise ScenarioError(f"No scenario spec at {path}.")
    try:
        return Spec.load(path).scenario()
    except (ModelscapeError, ValueError) as error:
        raise ScenarioError(f"{path}: {error}") from error


def _imported(reference: str) -> object:
    if "/" in reference or reference.endswith(".py"):
        name = ".".join(Path(reference.removesuffix(".py")).parts)
    else:
        name = reference
    if str(Path.cwd()) not in sys.path:
        sys.path.insert(0, str(Path.cwd()))
    try:
        module = import_module(name)
    except ModuleNotFoundError as error:
        if error.name is None or not f"{name}.".startswith(f"{error.name}."):
            raise
        names = ", ".join(available()) or "none"
        raise ScenarioError(
            f"No scenario named {reference}. Registered scenarios: {names}. A spec, module, "
            "or folder must be found from the current directory."
        ) from error
    return getattr(module, "SCENARIO", None)
