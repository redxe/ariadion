from __future__ import annotations

import cmath
from collections.abc import Sequence
from dataclasses import dataclass
from math import isclose, isfinite
from typing import Final

from ariadion_core import canonical_json
from ariadion_simulator import (
    EXPECTED_STATE_VECTOR_NORM,
    STATE_VECTOR_NORM_ABS_TOLERANCE,
    SimulationResult,
)


DEFAULT_EPSILON: Final = 1e-12
SEPARABILITY_ABS_TOLERANCE: Final = 1e-9


@dataclass(frozen=True, slots=True)
class BasisState:
    label: str
    amplitude: complex
    probability: float
    phase_radians: float

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "amplitude": _complex_to_dict(self.amplitude),
            "probability": self.probability,
            "phase_radians": self.phase_radians,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReducedDensityMatrix:
    """A one-qubit reduced density matrix derived from a pure state vector."""

    qubit_index: int
    rho_00: complex
    rho_01: complex
    rho_10: complex
    rho_11: complex
    purity: float
    is_separable_from_rest: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "qubit_index": self.qubit_index,
            "matrix": [
                [_complex_to_dict(self.rho_00), _complex_to_dict(self.rho_01)],
                [_complex_to_dict(self.rho_10), _complex_to_dict(self.rho_11)],
            ],
            "purity": self.purity,
            "is_separable_from_rest": self.is_separable_from_rest,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class SeparabilityReport:
    """Separability facts and explicitly heuristic subsystem groupings."""

    proven_fully_separable: bool
    proven_separable_qubits: tuple[int, ...]
    entangled_qubits: tuple[int, ...]
    heuristic_subsystems: tuple[tuple[int, ...], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "proven_fully_separable": self.proven_fully_separable,
            "proven_separable_qubits": list(self.proven_separable_qubits),
            "entangled_qubits": list(self.entangled_qubits),
            "heuristic_subsystems": [list(group) for group in self.heuristic_subsystems],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class StateReport:
    qubit_count: int
    states: tuple[BasisState, ...]
    entangled_qubits: tuple[int, ...]
    reduced_density_matrices: tuple[ReducedDensityMatrix, ...] = ()
    separability: SeparabilityReport | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "qubit_count": self.qubit_count,
            "states": [state.to_dict() for state in self.states],
            "entangled_qubits": list(self.entangled_qubits),
            "reduced_density_matrices": [
                matrix.to_dict() for matrix in self.reduced_density_matrices
            ],
            "separability": (
                self.separability.to_dict() if self.separability is not None else None
            ),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class BasisStateChange:
    """The amplitude, probability, and relative phase change for one basis state."""

    label: str
    before_amplitude: complex
    after_amplitude: complex
    before_probability: float
    after_probability: float
    phase_change_radians: float | None

    @property
    def probability_delta(self) -> float:
        return self.after_probability - self.before_probability

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "before_amplitude": _complex_to_dict(self.before_amplitude),
            "after_amplitude": _complex_to_dict(self.after_amplitude),
            "before_probability": self.before_probability,
            "after_probability": self.after_probability,
            "probability_delta": self.probability_delta,
            "phase_change_radians": self.phase_change_radians,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class EntanglementTransition:
    newly_entangled: tuple[int, ...]
    newly_separable: tuple[int, ...]
    persistent_entangled: tuple[int, ...]
    persistent_separable: tuple[int, ...]

    def to_dict(self) -> dict[str, list[int]]:
        return {
            "newly_entangled": list(self.newly_entangled),
            "newly_separable": list(self.newly_separable),
            "persistent_entangled": list(self.persistent_entangled),
            "persistent_separable": list(self.persistent_separable),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class StateTransition:
    """Structured Theonoe analysis for an immutable before/after state pair."""

    before: StateReport
    after: StateReport
    basis_state_changes: tuple[BasisStateChange, ...]
    entanglement: EntanglementTransition
    global_phase_delta_radians: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "basis_state_changes": [
                change.to_dict() for change in self.basis_state_changes
            ],
            "entanglement": self.entanglement.to_dict(),
            "global_phase_delta_radians": self.global_phase_delta_radians,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def inspect_state(
    result: SimulationResult,
    *,
    epsilon: float = DEFAULT_EPSILON,
    separability_tolerance: float = SEPARABILITY_ABS_TOLERANCE,
    normalization_tolerance: float = STATE_VECTOR_NORM_ABS_TOLERANCE,
) -> StateReport:
    """Inspect the final state of a simulation result."""

    return inspect_amplitudes(
        result.amplitudes,
        result.circuit.qubit_count,
        epsilon=epsilon,
        separability_tolerance=separability_tolerance,
        normalization_tolerance=normalization_tolerance,
    )


def inspect_amplitudes(
    amplitudes: Sequence[complex],
    qubit_count: int,
    *,
    epsilon: float = DEFAULT_EPSILON,
    separability_tolerance: float = SEPARABILITY_ABS_TOLERANCE,
    normalization_tolerance: float = STATE_VECTOR_NORM_ABS_TOLERANCE,
) -> StateReport:
    """Inspect an exact state-vector snapshot without requiring runtime contracts."""

    values = _validated_amplitudes(
        amplitudes,
        qubit_count,
        normalization_tolerance=normalization_tolerance,
    )
    _validate_non_negative_finite(epsilon, label="epsilon")
    _validate_non_negative_finite(
        separability_tolerance,
        label="separability_tolerance",
    )
    return _inspect_validated_amplitudes(
        values,
        qubit_count,
        epsilon=epsilon,
        separability_tolerance=separability_tolerance,
    )


def _inspect_validated_amplitudes(
    amplitudes: tuple[complex, ...],
    qubit_count: int,
    *,
    epsilon: float,
    separability_tolerance: float,
) -> StateReport:
    """Build a report from a previously validated normalized state vector."""

    states: list[BasisState] = []
    for index, amplitude in enumerate(amplitudes):
        probability = abs(amplitude) ** 2
        if probability <= epsilon:
            continue
        states.append(
            BasisState(
                label=_basis_label(index, qubit_count),
                amplitude=amplitude,
                probability=probability,
                phase_radians=cmath.phase(amplitude),
            )
        )

    reduced_density_matrices = tuple(
        _reduced_density_matrix_from_values(
            amplitudes,
            qubit_count,
            qubit,
            separability_tolerance=separability_tolerance,
        )
        for qubit in range(qubit_count)
    )
    proven_separable_qubits = tuple(
        matrix.qubit_index
        for matrix in reduced_density_matrices
        if matrix.is_separable_from_rest
    )
    entangled_qubits = tuple(
        matrix.qubit_index
        for matrix in reduced_density_matrices
        if not matrix.is_separable_from_rest
    )
    separability = SeparabilityReport(
        proven_fully_separable=not entangled_qubits,
        proven_separable_qubits=proven_separable_qubits,
        entangled_qubits=entangled_qubits,
        heuristic_subsystems=_heuristic_subsystems(qubit_count, entangled_qubits),
    )
    return StateReport(
        qubit_count,
        tuple(states),
        entangled_qubits,
        reduced_density_matrices,
        separability,
    )


def inspect_reduced_density_matrix(
    amplitudes: Sequence[complex],
    qubit_count: int,
    qubit_index: int,
    *,
    separability_tolerance: float = SEPARABILITY_ABS_TOLERANCE,
    normalization_tolerance: float = STATE_VECTOR_NORM_ABS_TOLERANCE,
) -> ReducedDensityMatrix:
    """Calculate one qubit's reduced density matrix and purity."""

    values = _validated_amplitudes(
        amplitudes,
        qubit_count,
        normalization_tolerance=normalization_tolerance,
    )
    _validate_non_negative_finite(
        separability_tolerance,
        label="separability_tolerance",
    )
    if isinstance(qubit_index, bool) or not isinstance(qubit_index, int):
        raise ValueError("qubit_index must be an integer")
    if not 0 <= qubit_index < qubit_count:
        raise ValueError("qubit_index must be within the state-vector width")
    return _reduced_density_matrix_from_values(
        values,
        qubit_count,
        qubit_index,
        separability_tolerance=separability_tolerance,
    )


def _reduced_density_matrix_from_values(
    amplitudes: tuple[complex, ...],
    qubit_count: int,
    qubit_index: int,
    *,
    separability_tolerance: float,
) -> ReducedDensityMatrix:
    """Build one reduced density matrix from validated normalized amplitudes."""

    mask = 1 << qubit_index
    rho_00 = 0j
    rho_11 = 0j
    rho_01 = 0j
    for base in range(1 << qubit_count):
        if base & mask:
            continue
        partner = base | mask
        zero, one = amplitudes[base], amplitudes[partner]
        rho_00 += zero * zero.conjugate()
        rho_11 += one * one.conjugate()
        rho_01 += zero * one.conjugate()
    rho_10 = rho_01.conjugate()
    purity = float((rho_00 * rho_00 + rho_11 * rho_11 + 2 * rho_01 * rho_10).real)
    return ReducedDensityMatrix(
        qubit_index,
        rho_00,
        rho_01,
        rho_10,
        rho_11,
        purity,
        purity >= 1 - separability_tolerance,
    )


def inspect_state_transition(
    before_amplitudes: Sequence[complex],
    after_amplitudes: Sequence[complex],
    qubit_count: int,
    *,
    epsilon: float = DEFAULT_EPSILON,
    separability_tolerance: float = SEPARABILITY_ABS_TOLERANCE,
    normalization_tolerance: float = STATE_VECTOR_NORM_ABS_TOLERANCE,
    before_report: StateReport | None = None,
    after_report: StateReport | None = None,
) -> StateTransition:
    """Inspect two snapshots and calculate their global-phase-invariant difference.

    `before_report` and `after_report` let callers reuse reports already produced
    for the corresponding normalized snapshots.
    """

    before_values = _validated_amplitudes(
        before_amplitudes,
        qubit_count,
        normalization_tolerance=normalization_tolerance,
    )
    after_values = _validated_amplitudes(
        after_amplitudes,
        qubit_count,
        normalization_tolerance=normalization_tolerance,
    )
    _validate_non_negative_finite(epsilon, label="epsilon")
    _validate_non_negative_finite(
        separability_tolerance,
        label="separability_tolerance",
    )
    before = before_report or _inspect_validated_amplitudes(
        before_values,
        qubit_count,
        epsilon=epsilon,
        separability_tolerance=separability_tolerance,
    )
    after = after_report or _inspect_validated_amplitudes(
        after_values,
        qubit_count,
        epsilon=epsilon,
        separability_tolerance=separability_tolerance,
    )
    _validate_precomputed_report(before, qubit_count, label="before_report")
    _validate_precomputed_report(after, qubit_count, label="after_report")
    canonical_before, _ = _canonicalize_global_phase(before_values)
    canonical_after, _ = _canonicalize_global_phase(after_values)
    basis_state_changes = _basis_state_changes(
        canonical_before,
        canonical_after,
        qubit_count,
        epsilon,
    )
    return StateTransition(
        before=before,
        after=after,
        basis_state_changes=basis_state_changes,
        entanglement=_entanglement_transition(
            before.entangled_qubits,
            after.entangled_qubits,
            qubit_count,
        ),
        global_phase_delta_radians=(
            _global_phase_delta(before_values, after_values)
            if _state_vectors_match(
                canonical_before,
                canonical_after,
                tolerance=normalization_tolerance,
            )
            else None
        ),
    )


def render_report(report: StateReport) -> str:
    lines = ["Theonoe state report", "--------------------"]
    for state in report.states:
        lines.append(
            f"{state.label:<8} p={state.probability:.6f} "
            f"amp={_format_complex(state.amplitude)} phase={state.phase_radians:+.6f} rad"
        )
    if report.entangled_qubits:
        qubits = ", ".join(f"q{index}" for index in report.entangled_qubits)
        lines.append(f"entanglement hint: mixed reduced states detected for {qubits}")
    else:
        lines.append("entanglement hint: none detected")
    if report.separability is not None:
        if report.separability.proven_fully_separable:
            lines.append("separability: fully separable from one-qubit purity checks")
        else:
            groups = ", ".join(
                "{" + ", ".join(f"q{qubit}" for qubit in group) + "}"
                for group in report.separability.heuristic_subsystems
            )
            lines.append(f"heuristic subsystems: {groups}")
    return "\n".join(lines)


def _basis_state_changes(
    before_amplitudes: tuple[complex, ...],
    after_amplitudes: tuple[complex, ...],
    qubit_count: int,
    epsilon: float,
) -> tuple[BasisStateChange, ...]:
    changes: list[BasisStateChange] = []
    for index, (before, after) in enumerate(zip(before_amplitudes, after_amplitudes)):
        if abs(after - before) ** 2 <= epsilon:
            continue
        before_probability = abs(before) ** 2
        after_probability = abs(after) ** 2
        phase_change = None
        if before_probability > epsilon and after_probability > epsilon:
            phase_change = cmath.phase(after * before.conjugate())
        changes.append(
            BasisStateChange(
                _basis_label(index, qubit_count),
                before,
                after,
                before_probability,
                after_probability,
                phase_change,
            )
        )
    return tuple(changes)


def _entanglement_transition(
    before_entangled: tuple[int, ...],
    after_entangled: tuple[int, ...],
    qubit_count: int,
) -> EntanglementTransition:
    before = set(before_entangled)
    after = set(after_entangled)
    all_qubits = set(range(qubit_count))
    return EntanglementTransition(
        newly_entangled=tuple(sorted(after - before)),
        newly_separable=tuple(sorted(before - after)),
        persistent_entangled=tuple(sorted(before & after)),
        persistent_separable=tuple(sorted(all_qubits - before - after)),
    )


def _heuristic_subsystems(
    qubit_count: int,
    entangled_qubits: tuple[int, ...],
) -> tuple[tuple[int, ...], ...]:
    entangled = set(entangled_qubits)
    groups = [(qubit,) for qubit in range(qubit_count) if qubit not in entangled]
    if entangled_qubits:
        groups.append(entangled_qubits)
    return tuple(sorted(groups, key=lambda group: group[0]))


def _validated_amplitudes(
    amplitudes: Sequence[complex],
    qubit_count: int,
    *,
    normalization_tolerance: float,
) -> tuple[complex, ...]:
    if isinstance(qubit_count, bool) or not isinstance(qubit_count, int):
        raise ValueError("qubit_count must be an integer")
    if qubit_count < 0:
        raise ValueError("qubit_count must be non-negative")
    values = tuple(amplitudes)
    if len(values) != 1 << qubit_count:
        raise ValueError("amplitude count must equal 2**qubit_count")
    if not all(isinstance(amplitude, complex) for amplitude in values):
        raise ValueError("amplitudes must be complex values")
    if any(
        not isfinite(amplitude.real) or not isfinite(amplitude.imag)
        for amplitude in values
    ):
        raise ValueError("amplitudes must be finite")
    _validate_non_negative_finite(
        normalization_tolerance,
        label="normalization_tolerance",
    )
    norm = sum(abs(amplitude) ** 2 for amplitude in values)
    if not isclose(
        norm,
        EXPECTED_STATE_VECTOR_NORM,
        rel_tol=0.0,
        abs_tol=normalization_tolerance,
    ):
        raise ValueError(
            "amplitudes must have unit norm within normalization_tolerance"
        )
    return values


def _validate_precomputed_report(
    report: StateReport,
    qubit_count: int,
    *,
    label: str,
) -> None:
    if not isinstance(report, StateReport):
        raise ValueError(f"{label} must be a StateReport")
    if report.qubit_count != qubit_count:
        raise ValueError(f"{label} qubit_count must match the state-vector width")


def _canonicalize_global_phase(
    amplitudes: tuple[complex, ...],
) -> tuple[tuple[complex, ...], float]:
    reference = max(amplitudes, key=abs)
    phase = cmath.phase(reference)
    factor = cmath.exp(-1j * phase)
    return tuple(amplitude * factor for amplitude in amplitudes), phase


def _global_phase_delta(
    before_amplitudes: tuple[complex, ...],
    after_amplitudes: tuple[complex, ...],
) -> float:
    reference_index = max(
        range(len(before_amplitudes)),
        key=lambda index: abs(before_amplitudes[index]),
    )
    return cmath.phase(
        after_amplitudes[reference_index]
        * before_amplitudes[reference_index].conjugate()
    )


def _state_vectors_match(
    before_amplitudes: tuple[complex, ...],
    after_amplitudes: tuple[complex, ...],
    *,
    tolerance: float,
) -> bool:
    return all(
        abs(after - before) <= tolerance
        for before, after in zip(before_amplitudes, after_amplitudes)
    )


def _validate_non_negative_finite(value: float, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    if not isfinite(float(value)) or value < 0:
        raise ValueError(f"{label} must be finite and non-negative")


def _basis_label(index: int, qubit_count: int) -> str:
    return f"|{index:0{qubit_count}b}>"


def _complex_to_dict(value: complex) -> dict[str, float]:
    return {"real": value.real, "imaginary": value.imag}


def _format_complex(value: complex) -> str:
    return f"{value.real:+.6f}{value.imag:+.6f}i"
