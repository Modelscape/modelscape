"""Requirements on a report, such as ``accuracy>=0.9`` or ``sensitive:invariant_shifts==0``.

Each applies to every scorecard, or to one case group's; quantities a scorecard could not
measure are skipped.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable, Collection, Sequence
from typing import Literal, TypeAlias, get_args

from modelscape.analysis import Divergence, Scorecard
from modelscape.core.errors import RequirementError
from modelscape.core.serialization import FrozenModel
from modelscape.report import Report

Quantity: TypeAlias = Literal[
    "accuracy", "answered", "spurious_change", "missed_change", "invariant_shifts", "divergences"
]
Comparison: TypeAlias = Literal["<=", ">=", "==", "<", ">"]

COMPARISONS: dict[str, Callable[[float, float], bool]] = {
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "<": operator.lt,
    ">": operator.gt,
}
PATTERN = re.compile(r"^\s*(?:([^:\s]+)\s*:)?\s*(\w+)\s*(<=|>=|==|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")


class Requirement(FrozenModel):
    """A bound on one report quantity, such as ``accuracy>=0.9`` or ``control:accuracy>=0.9``."""

    quantity: Quantity
    comparison: Comparison
    threshold: float
    group: str | None = None

    @classmethod
    def parse(cls, text: str) -> Requirement:
        match = PATTERN.match(text)
        if match is None or match[2] not in get_args(Quantity):
            raise RequirementError(
                f"Cannot read requirement {text!r}. Write [group:]<quantity><comparison><number>, "
                f"such as accuracy>=0.9, with a quantity in {', '.join(get_args(Quantity))}."
            )
        if match[1] is not None and match[2] == "divergences":
            raise RequirementError(
                f"Cannot read requirement {text!r}: divergences are compared over every case, "
                "not per group."
            )
        return cls.model_validate(
            {
                "group": match[1],
                "quantity": match[2],
                "comparison": match[3],
                "threshold": float(match[4]),
            }
        )

    def __str__(self) -> str:
        scope = f"{self.group}:" if self.group is not None else ""
        return f"{scope}{self.quantity}{self.comparison}{self.threshold:g}"

    def violations(self, report: Report, targets: Collection[str] | None = None) -> list[str]:
        """One line for every scorecard or divergence in scope that misses this requirement.

        ``targets`` limits the requirement to those targets; a divergence belongs to the target
        compared with the first.
        """
        if self.quantity == "divergences":
            measured = [
                (_divergence_label(item), float(len(item.candidates)))
                for item in report.divergences
                if targets is None or item.second in targets
            ]
        else:
            cards = [
                card
                for card in report.scorecards
                if (targets is None or card.target in targets)
                and (self.group is None or card.group == self.group)
            ]
            if self.group is not None and not cards:
                groups = sorted({card.group for card in report.scorecards})
                raise RequirementError(
                    f"Requirement {self} names group {self.group!r}, but the report has groups "
                    f"{', '.join(groups)}."
                )
            measured = [(_scorecard_label(card), self._value(card)) for card in cards]
        holds = COMPARISONS[self.comparison]
        return [
            f"{label}: {self.quantity} is {value:.3g}, required {self.comparison} "
            f"{self.threshold:g}"
            for label, value in measured
            if value is not None and not holds(value, self.threshold)
        ]

    def _value(self, card: Scorecard) -> float | None:
        if self.quantity == "accuracy":
            return card.accuracy.value
        if self.quantity == "answered":
            return card.answered
        if self.quantity == "spurious_change":
            return card.spurious_change
        if self.quantity == "missed_change":
            return card.missed_change
        return float(card.invariant_shifts)


def check(
    report: Report,
    requirements: Sequence[Requirement],
    targets: Collection[str] | None = None,
) -> list[str]:
    """Every violation of every requirement; an empty list means the report passes.

    ``targets`` limits every requirement to those targets, which must all be in the report.
    """
    if targets is not None:
        known = {card.target for card in report.scorecards}
        unknown = sorted(set(targets) - known)
        if unknown:
            raise RequirementError(
                f"Targets {', '.join(unknown)} are not in the report, which has targets "
                f"{', '.join(sorted(known))}."
            )
    return [
        line for requirement in requirements for line in requirement.violations(report, targets)
    ]


def _scorecard_label(card: Scorecard) -> str:
    return f"{card.target} {card.group}"


def _divergence_label(divergence: Divergence) -> str:
    return f"{divergence.second} versus {divergence.first}"
