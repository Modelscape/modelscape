"""Lexicons that ship with modelscape, ready to fill template slots by name.

``names`` holds 70 full names, five for each of two genders in seven regions, so ``gender`` and
``region`` swaps pair every name with a counterpart of the same rank. ``roles``, ``pressure``,
``injections``, and ``tones`` each start with an empty entry, so a slot filled from them leaves
the baseline prompt as it was.
"""

from functools import cache
from pathlib import Path

from modelscape.template import Lexicon

FOLDER = Path(__file__).parent


def available() -> tuple[str, ...]:
    """The name of every shipped lexicon."""
    return tuple(sorted(path.stem for path in FOLDER.glob("*.yaml")))


@cache
def get(name: str) -> Lexicon:
    """The shipped lexicon called ``name``."""
    if name not in available():
        raise ValueError(f"No lexicon is called '{name}'; shipped: {', '.join(available())}.")
    return Lexicon.load(FOLDER / f"{name}.yaml")


__all__ = ["available", "get"]
