from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite, pi, tau

from ariadion_core import canonical_json


class AngleUnit(str, Enum):
    """The explicit unit supplied by a source-level rotation angle."""

    RADIANS = "radians"
    DEGREES = "degrees"
    TURNS = "turns"


@dataclass(frozen=True, slots=True)
class Angle:
    """An explicit source angle with a canonical radians representation."""

    source_value: float
    source_unit: AngleUnit
    radians: float = field(init=False)

    def __post_init__(self) -> None:
        if isinstance(self.source_value, bool) or not isinstance(
            self.source_value,
            (int, float),
        ):
            raise ValueError("angle source_value must be numeric")
        source_value = float(self.source_value)
        if not isfinite(source_value):
            raise ValueError("angle source_value must be finite")
        if not isinstance(self.source_unit, AngleUnit):
            raise ValueError("angle source_unit must be an AngleUnit")

        factor = {
            AngleUnit.RADIANS: 1.0,
            AngleUnit.DEGREES: pi / 180,
            AngleUnit.TURNS: tau,
        }[self.source_unit]
        radians = source_value * factor
        if not isfinite(radians):
            raise ValueError("angle radians must be finite")
        object.__setattr__(self, "source_value", source_value)
        object.__setattr__(self, "radians", radians)

    def to_dict(self) -> dict[str, float | str]:
        return {
            "source_value": self.source_value,
            "source_unit": self.source_unit.value,
            "radians": self.radians,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def deg(value: float | int) -> Angle:
    """Create an angle explicitly expressed in degrees."""

    return Angle(value, AngleUnit.DEGREES)


def rad(value: float | int) -> Angle:
    """Create an angle explicitly expressed in radians."""

    return Angle(value, AngleUnit.RADIANS)


def turns(value: float | int) -> Angle:
    """Create an angle explicitly expressed in complete turns."""

    return Angle(value, AngleUnit.TURNS)
