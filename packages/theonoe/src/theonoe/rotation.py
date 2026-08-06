from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isclose, isfinite, pi, tau
from typing import Final

from ariadion_core import canonical_json

from .inspector import DEFAULT_EPSILON, StateTransition


_SOURCE_ANGLE_UNIT_TO_RADIANS = {
    "degrees": pi / 180,
    "radians": 1.0,
    "turns": tau,
}
_SOURCE_ANGLE_ABS_TOLERANCE: Final = 1e-12
_SOURCE_ANGLE_REL_TOLERANCE: Final = 1e-15


class RotationAxis(str, Enum):
    """The Bloch-sphere axis for a one-qubit rotation."""

    X = "X"
    Y = "Y"
    Z = "Z"


class RotationEffect(str, Enum):
    """The exact state-level effect classified from an inspected transition."""

    PROBABILITIES_CHANGED = "probabilities_changed"
    RELATIVE_PHASE_ONLY = "relative_phase_only"
    GLOBAL_PHASE_ONLY = "global_phase_only"
    NO_VISIBLE_CHANGE = "no_visible_change"


@dataclass(frozen=True, slots=True)
class RotationSourceAngle:
    """An optional source-unit angle retained for a rotation explanation."""

    source_value: float
    source_unit: str

    def __post_init__(self) -> None:
        if isinstance(self.source_value, bool) or not isinstance(
            self.source_value,
            (int, float),
        ):
            raise ValueError("rotation source_value must be numeric")
        source_value = float(self.source_value)
        if not isfinite(source_value):
            raise ValueError("rotation source_value must be finite")
        if (
            not isinstance(self.source_unit, str)
            or self.source_unit not in _SOURCE_ANGLE_UNIT_TO_RADIANS
        ):
            raise ValueError("rotation source_unit must be degrees, radians, or turns")
        object.__setattr__(self, "source_value", source_value)

    def to_dict(self) -> dict[str, float | str]:
        return {
            "source_value": self.source_value,
            "source_unit": self.source_unit,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class RotationExplanation:
    """Exact trace facts and a separately labeled educational rotation model."""

    target: int
    axis: RotationAxis
    angle_radians: float
    source_angle: RotationSourceAngle | None
    probabilities_changed: bool
    relative_phase_changed: bool
    effect: RotationEffect
    global_phase_delta_radians: float | None
    exact_claims: tuple[str, ...]
    educational_interpretation: str

    def __post_init__(self) -> None:
        if isinstance(self.target, bool) or not isinstance(self.target, int):
            raise ValueError("rotation target must be an integer")
        if self.target < 0:
            raise ValueError("rotation target must be non-negative")
        if not isinstance(self.axis, RotationAxis):
            raise ValueError("rotation axis must be a RotationAxis")
        if isinstance(self.angle_radians, bool) or not isinstance(
            self.angle_radians,
            (int, float),
        ):
            raise ValueError("rotation angle_radians must be numeric")
        angle_radians = float(self.angle_radians)
        if not isfinite(angle_radians):
            raise ValueError("rotation angle_radians must be finite")
        if self.source_angle is not None and not isinstance(
            self.source_angle,
            RotationSourceAngle,
        ):
            raise ValueError("rotation source_angle must be RotationSourceAngle")
        if not isinstance(self.probabilities_changed, bool):
            raise ValueError("rotation probabilities_changed must be a boolean")
        if not isinstance(self.relative_phase_changed, bool):
            raise ValueError("rotation relative_phase_changed must be a boolean")
        if not isinstance(self.effect, RotationEffect):
            raise ValueError("rotation effect must be a RotationEffect")
        if self.global_phase_delta_radians is not None and (
            isinstance(self.global_phase_delta_radians, bool)
            or not isinstance(self.global_phase_delta_radians, (int, float))
            or not isfinite(float(self.global_phase_delta_radians))
        ):
            raise ValueError("rotation global_phase_delta_radians must be finite")
        if not isinstance(self.exact_claims, tuple) or not all(
            isinstance(claim, str) and claim for claim in self.exact_claims
        ):
            raise ValueError("rotation exact_claims must be non-empty strings in a tuple")
        if (
            not isinstance(self.educational_interpretation, str)
            or not self.educational_interpretation
        ):
            raise ValueError("rotation educational_interpretation must be a non-empty string")
        object.__setattr__(self, "angle_radians", angle_radians)

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "axis": self.axis.value,
            "angle_radians": self.angle_radians,
            "source_angle": (
                self.source_angle.to_dict() if self.source_angle is not None else None
            ),
            "probabilities_changed": self.probabilities_changed,
            "relative_phase_changed": self.relative_phase_changed,
            "effect": self.effect.value,
            "global_phase_delta_radians": self.global_phase_delta_radians,
            "exact_claims": list(self.exact_claims),
            "educational_interpretation": self.educational_interpretation,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def explain_rotation_transition(
    transition: StateTransition,
    *,
    target: int,
    axis: RotationAxis,
    angle_radians: float,
    source_angle: RotationSourceAngle | None = None,
    epsilon: float = DEFAULT_EPSILON,
) -> RotationExplanation:
    """Explain an inspected rotation without depending on runtime trace contracts."""

    if not isinstance(transition, StateTransition):
        raise ValueError("rotation transition must be a StateTransition")
    _validate_non_negative_finite(epsilon, label="epsilon")
    _validate_target(target, qubit_count=transition.before.qubit_count)
    _validate_axis(axis)
    _validate_finite_angle(angle_radians)
    if source_angle is not None and not isinstance(source_angle, RotationSourceAngle):
        raise ValueError("rotation source_angle must be RotationSourceAngle")
    if source_angle is not None:
        _validate_source_angle_consistency(source_angle, float(angle_radians))

    probabilities_changed = any(
        abs(change.probability_delta) > epsilon
        for change in transition.basis_state_changes
    )
    relative_phase_changed = any(
        change.phase_change_radians is not None
        and abs(change.phase_change_radians) > epsilon
        for change in transition.basis_state_changes
    )
    global_phase_delta = transition.global_phase_delta_radians
    global_phase_reported = (
        global_phase_delta is not None and abs(global_phase_delta) > epsilon
    )
    effect = _rotation_effect(
        probabilities_changed,
        relative_phase_changed,
        global_phase_reported,
    )
    return RotationExplanation(
        target=target,
        axis=axis,
        angle_radians=float(angle_radians),
        source_angle=source_angle,
        probabilities_changed=probabilities_changed,
        relative_phase_changed=relative_phase_changed,
        effect=effect,
        global_phase_delta_radians=global_phase_delta,
        exact_claims=_exact_claims(
            target=target,
            axis=axis,
            angle_radians=float(angle_radians),
            probabilities_changed=probabilities_changed,
            relative_phase_changed=relative_phase_changed,
            global_phase_delta_radians=global_phase_delta,
            global_phase_reported=global_phase_reported,
        ),
        educational_interpretation=_educational_interpretation(target, axis),
    )


def _rotation_effect(
    probabilities_changed: bool,
    relative_phase_changed: bool,
    global_phase_reported: bool,
) -> RotationEffect:
    if probabilities_changed:
        return RotationEffect.PROBABILITIES_CHANGED
    if relative_phase_changed:
        return RotationEffect.RELATIVE_PHASE_ONLY
    if global_phase_reported:
        return RotationEffect.GLOBAL_PHASE_ONLY
    return RotationEffect.NO_VISIBLE_CHANGE


def _exact_claims(
    *,
    target: int,
    axis: RotationAxis,
    angle_radians: float,
    probabilities_changed: bool,
    relative_phase_changed: bool,
    global_phase_delta_radians: float | None,
    global_phase_reported: bool,
) -> tuple[str, ...]:
    claims = [
        f"{axis.value}-axis rotation of q{target} by {angle_radians:.12g} rad.",
        (
            "Computational-basis probabilities changed in this exact transition."
            if probabilities_changed
            else "Computational-basis probabilities did not change in this exact transition."
        ),
        (
            "A relative phase changed between visible basis states."
            if relative_phase_changed
            else "No relative phase change was detected between visible basis states."
        ),
    ]
    if axis is RotationAxis.Z:
        claims.append(
            "RZ is diagonal in the computational basis, so it preserves "
            "computational-basis probabilities."
        )
    if global_phase_reported:
        assert global_phase_delta_radians is not None
        claims.append(
            "A global phase of "
            f"{global_phase_delta_radians:+.12g} rad was reported; global phase "
            "is unobservable."
        )
    return tuple(claims)


def _educational_interpretation(target: int, axis: RotationAxis) -> str:
    if axis is RotationAxis.X:
        return (
            f"An X-axis rotation turns q{target} around the Bloch sphere's X axis. "
            "Its visible probability and relative-phase effects depend on the "
            "incoming state."
        )
    if axis is RotationAxis.Y:
        return (
            f"A Y-axis rotation turns q{target} along a Bloch-sphere meridian. "
            "It can redistribute |0> and |1> measurement weight."
        )
    return (
        f"A Z-axis rotation moves q{target} around the Bloch sphere's vertical axis. "
        "It can affect later interference even when an immediate "
        "computational-basis measurement is unchanged."
    )


def _validate_target(target: int, *, qubit_count: int) -> None:
    if isinstance(target, bool) or not isinstance(target, int) or target < 0:
        raise ValueError("rotation target must be a non-negative integer")
    if target >= qubit_count:
        raise ValueError("rotation target must select a qubit in the transition")


def _validate_axis(axis: RotationAxis) -> None:
    if not isinstance(axis, RotationAxis):
        raise ValueError("rotation axis must be a RotationAxis")


def _validate_finite_angle(angle_radians: float) -> None:
    if isinstance(angle_radians, bool) or not isinstance(angle_radians, (int, float)):
        raise ValueError("rotation angle_radians must be numeric")
    if not isfinite(float(angle_radians)):
        raise ValueError("rotation angle_radians must be finite")


def _validate_source_angle_consistency(
    source_angle: RotationSourceAngle,
    angle_radians: float,
) -> None:
    expected_angle_radians = (
        source_angle.source_value
        * _SOURCE_ANGLE_UNIT_TO_RADIANS[source_angle.source_unit]
    )
    if not isfinite(expected_angle_radians) or not isclose(
        angle_radians,
        expected_angle_radians,
        rel_tol=_SOURCE_ANGLE_REL_TOLERANCE,
        abs_tol=_SOURCE_ANGLE_ABS_TOLERANCE,
    ):
        raise ValueError("rotation source_angle must match angle_radians")


def _validate_non_negative_finite(value: float, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    if not isfinite(float(value)) or value < 0:
        raise ValueError(f"{label} must be finite and non-negative")
