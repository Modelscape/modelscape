"""Scenarios written as YAML: a prompt with slots, what to vary, and the correct answer.

name: refunds
prompt: "{person} asks for ${amount} back. {appeal}"
slots:
  person: names
  amount: {from: 100, to: 900, step: 400}
  appeal: pressure
vary:
  person.gender: nominal
  appeal: ordinal
  amount: numeric
answer:
  field: decision
  choices: [approve, escalate]
  correct:
    - when: {amount: {at_least: 500}}
      then: escalate
    - then: approve
groups:
  large: {amount: {at_least: 500}}
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    StrictFloat,
    StrictInt,
    ValidationError,
    model_validator,
)

from modelscape import lexicons
from modelscape.analysis.threshold import Answer as AnswerReader
from modelscape.core.coordinates import Scale, is_number, same_value
from modelscape.core.errors import SpecError, TaskSpaceError
from modelscape.core.experiments import Grid, Sweep
from modelscape.core.files import format_yaml, parse_yaml
from modelscape.core.serialization import AxisValue, FrozenModel
from modelscape.scenario import Scenario, json_field, text_match
from modelscape.space import Axis, TaskSpace
from modelscape.template import Entry, Filling, Lexical, Lexicon, Template

Number: TypeAlias = StrictInt | StrictFloat
RANGE_LIMIT = 1000


class Range(FrozenModel):
    """Every number from ``from`` up to ``to``, ``step`` apart, written ``{from:, to:, step:}``.

    Each number is both the label and the text of its entry.
    """

    start: Number = Field(alias="from", allow_inf_nan=False)
    stop: Number = Field(alias="to", allow_inf_nan=False)
    step: Number = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _ascending(self) -> Range:
        if self.stop <= self.start:
            raise ValueError("A range goes up: 'to' must be above 'from'.")
        if len(self._steps()) > RANGE_LIMIT:
            raise ValueError(f"A range holds at most {RANGE_LIMIT} numbers.")
        return self

    @property
    def values(self) -> tuple[Number, ...]:
        steps = self._steps()
        if all(isinstance(bound, int) for bound in (self.start, self.step)):
            return tuple(int(value) for value in steps)
        return tuple(float(value) for value in steps)

    def lexicon(self) -> Lexicon:
        return Lexicon(
            entries=tuple(Entry(label=value, text=_spelled(value)) for value in self.values)
        )

    def data(self) -> dict[str, Number]:
        return self.model_dump(by_alias=True)

    def _steps(self) -> list[Decimal]:
        start, stop, step = (Decimal(str(bound)) for bound in (self.start, self.stop, self.step))
        count = int((stop - start) // step) + 1
        return [start + index * step for index in range(min(count, RANGE_LIMIT + 1))]


def _spelled(value: Number) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _lexicon(value: object) -> object:
    if isinstance(value, str | Lexicon | Range):
        return value
    if isinstance(value, dict) and value.keys() == {"from", "to", "step"}:
        return Range.model_validate(value)
    if not isinstance(value, list | dict):
        raise ValueError(f"A slot is a lexicon name, a list, a mapping, or a range, got {value!r}.")
    return Lexicon.of(cast(Lexical, value))


def filled(slot: object) -> Lexicon:
    """The lexicon of a slot as written in a spec: a lexicon's name, its values, or a range."""
    lexicon = _lexicon(slot)
    if isinstance(lexicon, str):
        return lexicons.get(lexicon)
    if isinstance(lexicon, Range):
        return lexicon.lexicon()
    return cast(Lexicon, lexicon)


def range_of(slot: object) -> Range | None:
    """The range a slot is written as, if it is one."""
    lexicon = _lexicon(slot)
    return lexicon if isinstance(lexicon, Range) else None


Text: TypeAlias = Annotated[str, AfterValidator(str.strip)]
Slot: TypeAlias = Annotated[Lexicon | Range | str, BeforeValidator(_lexicon)]


class Bound(FrozenModel):
    """The numbers ``at_least`` one value and ``below`` another; either may be left out."""

    at_least: Number | None = Field(default=None, allow_inf_nan=False)
    below: Number | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def _bounded(self) -> Bound:
        if self.at_least is None and self.below is None:
            raise ValueError("A bound needs at_least, below, or both.")
        if self.at_least is not None and self.below is not None and self.below <= self.at_least:
            raise ValueError("A bound's below must be above its at_least.")
        return self

    def holds(self, value: AxisValue) -> bool:
        return (
            is_number(value)
            and (self.at_least is None or value >= self.at_least)
            and (self.below is None or value < self.below)
        )


Conditions: TypeAlias = dict[str, AxisValue | Bound]


class Rule(FrozenModel):
    """The answer ``then`` for variants whose attributes match every entry of ``when``.

    An entry is a value, or a ``Bound`` on a numeric attribute such as ``{at_least: 500}``.
    """

    when: Conditions = Field(default_factory=Conditions)
    then: AxisValue

    def matches(self, attributes: Mapping[str, AxisValue]) -> bool:
        return _matches(self.when, attributes)


def _matches(conditions: Conditions, attributes: Mapping[str, AxisValue]) -> bool:
    return all(
        name in attributes and _meets(condition, attributes[name])
        for name, condition in conditions.items()
    )


def _meets(condition: AxisValue | Bound, value: AxisValue) -> bool:
    if isinstance(condition, Bound):
        return condition.holds(value)
    return same_value(value, condition)


Correct: TypeAlias = AxisValue | dict[str, dict[AxisValue, AxisValue]] | tuple[Rule, ...]


class Varied(FrozenModel):
    """How one attribute varies: its scale, and any values and baseline other than the default."""

    scale: Scale
    values: tuple[AxisValue, ...] | None = None
    baseline: AxisValue | None = None


class Answer(FrozenModel):
    """Where the answer is in a reply, its choices, and which one is correct.

    The answer is ``field`` of a JSON reply, or the first match of the regular expression
    ``pattern``, its first group if it has one. ``correct`` is one choice; a table from the
    values of one attribute to choices; or rules, where the first rule whose ``when`` matches
    gives the answer and the last rule, without ``when``, gives it otherwise.
    """

    field: str | None = None
    pattern: str | None = None
    choices: tuple[AxisValue, ...] = Field(min_length=2)
    correct: Correct

    @model_validator(mode="after")
    def _read_one_way(self) -> Answer:
        if (self.field is None) == (self.pattern is None):
            raise ValueError("An answer is read from either a field or a pattern.")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as error:
                raise ValueError(f"The pattern {self.pattern!r} is not valid: {error}.") from error
        return self

    @property
    def read(self) -> AnswerReader:
        """The function that reads this answer from an output."""
        if self.field is not None:
            return json_field(self.field, self.choices)
        return text_match(cast(str, self.pattern), self.choices)

    @model_validator(mode="after")
    def _within_choices(self) -> Answer:
        if isinstance(self.correct, tuple):
            *conditional, last = self.correct or (None,)
            if last is None or last.when:
                raise ValueError("The last rule gives the answer otherwise, without when.")
            if any(not rule.when for rule in conditional):
                raise ValueError("Every rule but the last needs a when.")
            answers = [rule.then for rule in self.correct]
        elif not isinstance(self.correct, dict):
            answers = [self.correct]
        elif len(self.correct) == 1:
            answers = list(self.table.values())
        else:
            raise ValueError("correct depends on exactly one attribute.")
        for answer in answers:
            if not any(same_value(answer, choice) for choice in self.choices):
                raise ValueError(f"The correct answer {answer!r} is not one of the choices.")
        return self

    @property
    def attribute(self) -> str | None:
        return next(iter(self.correct)) if isinstance(self.correct, dict) else None

    @property
    def rules(self) -> tuple[Rule, ...]:
        return self.correct if isinstance(self.correct, tuple) else ()

    @property
    def table(self) -> dict[AxisValue, AxisValue]:
        return next(iter(self.correct.values())) if isinstance(self.correct, dict) else {}

    def of(self, attributes: Mapping[str, AxisValue]) -> AxisValue:
        """The correct answer of a variant with ``attributes``."""
        if self.rules:
            return next(rule.then for rule in self.rules if rule.matches(attributes))
        if self.attribute is None:
            return cast(AxisValue, self.correct)
        value = attributes[self.attribute]
        for key, answer in self.table.items():
            if same_value(key, value):
                return answer
        raise TaskSpaceError(f"answer.correct: {self.attribute}={value!r} has no answer.")


class Spec(FrozenModel):
    """A scenario written as data, read from and written to YAML.

    ``prompt`` is one text, or versions of the whole prompt under one attribute name, such as
    ``{friendliness: {neutral: ..., polite: ...}}``. ``slots`` fill the prompt's
    ``{placeholders}``; each is a shipped lexicon by name, a list of values, a mapping of labels
    to texts, a list of rows, or a ``Range`` of numbers. A text may be one text per prompt
    version. ``vary`` maps each attribute to vary to its scale, or to a ``Varied``. ``groups``
    name the cases whose attributes match their conditions, each with its own scorecard.
    """

    name: str
    version: int | str = 1
    description: str = ""
    system: Text | None = None
    prompt: Text | dict[str, dict[AxisValue, Text]]
    slots: dict[str, Slot]
    vary: dict[str, Scale | Varied] = Field(min_length=1)
    answer: Answer
    cases: int | None = Field(default=None, ge=1)
    seed: int = 0
    repetitions: int = Field(default=5, ge=1)
    design: Literal["sweep", "grid"] = "sweep"
    groups: dict[str, Conditions] = Field(default_factory=dict[str, Conditions])

    @model_validator(mode="after")
    def _one_version_attribute(self) -> Spec:
        if isinstance(self.prompt, dict) and len(self.prompt) != 1:
            raise ValueError("Prompt versions map one attribute name to its versions.")
        return self

    @classmethod
    def of(cls, data: object) -> Spec:
        """The spec in ``data``, as read from YAML; raises ``SpecError`` naming every problem."""
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise SpecError(
                "; ".join(
                    f"{'.'.join(map(str, item['loc'])) or 'spec'}: "
                    f"{item['msg'].removeprefix('Value error, ')}"
                    for item in error.errors()
                )
            ) from error

    @classmethod
    def parse(cls, text: str) -> Spec:
        """The spec in a YAML document."""
        return cls.of(parse_yaml(text))

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Spec:
        """The spec in a YAML file."""
        return cls.parse(Path(path).read_text(encoding="utf-8"))

    def dump(self) -> str:
        """The spec as YAML, with every lexicon in its shortest form."""
        data = self.model_dump(exclude_defaults=True)
        data["slots"] = {
            slot: value if isinstance(value, str) else value.data()
            for slot, value in self.slots.items()
        }
        return format_yaml(data)

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the spec as a YAML file and return its path."""
        target = Path(path)
        target.write_text(self.dump(), encoding="utf-8")
        return target

    def lexicon(self, slot: str) -> Lexicon:
        """The lexicon that fills ``slot``."""
        return filled(self.slots[slot])

    def template(self) -> Template:
        """The template the spec describes."""
        return Template(
            self.prompt,
            {slot: self.lexicon(slot) for slot in self.slots},
            name=self.name,
            system=self.system,
            reference=self.answer.of,
        )

    def scenario(self) -> Scenario:
        """The scenario the spec describes; every variant is checked as it is generated."""
        template = self.template()
        if self.answer.attribute is not None:
            for value in template.values(self.answer.attribute):
                self.answer.of({self.answer.attribute: value})
        for rule in self.answer.rules:
            for name, condition in rule.when.items():
                values = template.values(name)
                if isinstance(condition, Bound) and not all(map(is_number, values)):
                    raise TaskSpaceError(f"answer.correct: {name} has values that are not numbers.")
                if not any(_meets(condition, value) for value in values):
                    raise TaskSpaceError(
                        f"answer.correct: {name} has no value {_shown(condition)}."
                    )
        space = template.space(
            [_axis(template, name, varied) for name, varied in self.vary.items()],
            cases=self.cases,
            seed=self.seed,
        )
        return Scenario(
            name=self.name,
            version=str(self.version),
            description=self.description,
            task_space=space,
            answer=self.answer.read,
            repetitions=self.repetitions,
            design=Grid() if self.design == "grid" else Sweep(),
            groups={name: _group(space, name, when) for name, when in self.groups.items()},
        )


def _group(space: TaskSpace[Filling], name: str, conditions: Conditions) -> tuple[str, ...]:
    cases = tuple(
        case for case, task in space.cases.items() if _matches(conditions, task.attributes())
    )
    if not cases:
        raise TaskSpaceError(f"groups.{name}: no case matches {conditions}.")
    return cases


def _axis(template: Template, attribute: str, varied: Scale | Varied) -> Axis[Filling, Any]:
    if isinstance(varied, str):
        return template.axis(attribute, varied)
    return template.axis(attribute, varied.scale, varied.values, baseline=varied.baseline)


def _shown(condition: AxisValue | Bound) -> str:
    if not isinstance(condition, Bound):
        return repr(condition)
    parts = [
        f"{word} {bound}"
        for word, bound in (("at least", condition.at_least), ("below", condition.below))
        if bound is not None
    ]
    return " and ".join(parts)
