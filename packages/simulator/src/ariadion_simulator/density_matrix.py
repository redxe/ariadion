"""Small exact density-matrix execution for typed Ariadion noise channels.

This backend deliberately remains separate from the reference state-vector path.
It evolves $\rho$ exactly for small circuits, applies configured single-qubit
channels after their ideal gates, supports exact reset, and retains terminal
measurement probabilities without introducing classical feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, isclose, isfinite, sin, sqrt
from typing import Final, TypeAlias

from ariadion_ir import CircuitIR, IrOperationId, OpCode, Operation
from ariadion_noise import (
    ExecutableNoiseModel,
    KrausOperator,
    OneQubitGate,
    QuantumChannel,
    validate_executable_noise_model,
    validate_quantum_channel,
)


DENSITY_MATRIX_ABS_TOLERANCE: Final = 1e-12
DensityMatrix: TypeAlias = tuple[tuple[complex, ...], ...]

_ONE_QUBIT_GATE_BY_OPCODE = {
    OpCode.X: OneQubitGate.X,
    OpCode.H: OneQubitGate.H,
    OpCode.Z: OneQubitGate.Z,
    OpCode.RX: OneQubitGate.RX,
    OpCode.RY: OneQubitGate.RY,
    OpCode.RZ: OneQubitGate.RZ,
}


class DensityMatrixInvariantError(ValueError):
    """Raised when a density matrix violates its public result invariants."""


class DensityMatrixTerminalObservationError(ValueError):
    """Raised when density-matrix execution encounters a post-observation operation."""

    code: Final = "A202"

    def __init__(
        self,
        *,
        observed_operation_id: IrOperationId,
        observed_step_index: int,
        following_operation_id: IrOperationId,
        following_step_index: int,
    ) -> None:
        self.observed_operation_id = observed_operation_id
        self.observed_step_index = observed_step_index
        self.following_operation_id = following_operation_id
        self.following_step_index = following_step_index
        super().__init__(
            f"{self.code}: exact density-matrix execution supports terminal observations only "
            f"(observation at step {observed_step_index}, later operation at step "
            f"{following_step_index})"
        )


@dataclass(frozen=True, slots=True)
class DensityMatrixExecutionRequest:
    """Explicitly select exact density-matrix execution and its typed noise model."""

    noise_model: ExecutableNoiseModel = field(default_factory=ExecutableNoiseModel)

    def __post_init__(self) -> None:
        if not isinstance(self.noise_model, ExecutableNoiseModel):
            raise ValueError(
                "density-matrix execution noise_model must be an ExecutableNoiseModel"
            )


@dataclass(frozen=True, slots=True)
class DensityMatrixResult:
    """A final exact mixed state distinct from state-vector amplitudes."""

    circuit: CircuitIR
    density_matrix: DensityMatrix

    def __post_init__(self) -> None:
        if not isinstance(self.circuit, CircuitIR):
            raise DensityMatrixInvariantError("density-matrix result circuit must be CircuitIR")
        if not isinstance(self.density_matrix, tuple) or not all(
            isinstance(row, tuple) for row in self.density_matrix
        ):
            raise DensityMatrixInvariantError("density matrix must be an immutable tuple of rows")
        _validate_density_matrix(self.density_matrix, qubit_count=self.circuit.qubit_count)

    @property
    def probabilities(self) -> tuple[float, ...]:
        """Return computational-basis probabilities from the diagonal of $\rho$."""

        return tuple(value.real for value in _matrix_diagonal(self.density_matrix))


def simulate_density_matrix(
    circuit: CircuitIR,
    *,
    execution: DensityMatrixExecutionRequest | None = None,
) -> DensityMatrixResult:
    """Run ideal or explicitly configured noisy exact density-matrix execution.

    Every configured channel is resolved through its neutral public gate category,
    then applied after the matching ideal single-qubit operation. Unbound opcodes
    remain ideal. No trace argument exists because current traces are amplitude-only.
    """

    if not isinstance(circuit, CircuitIR):
        raise ValueError("density-matrix simulation circuit must be CircuitIR")
    request = execution if execution is not None else DensityMatrixExecutionRequest()
    if not isinstance(request, DensityMatrixExecutionRequest):
        raise ValueError(
            "density-matrix simulation execution must be DensityMatrixExecutionRequest"
        )
    validate_executable_noise_model(request.noise_model)

    dimension = 1 << circuit.qubit_count
    density = _zero_density_matrix(dimension)
    density[0][0] = 1 + 0j
    terminal_observation: tuple[IrOperationId, int] | None = None

    for step_index, operation in enumerate(circuit.operations):
        if terminal_observation is not None and operation.opcode is not OpCode.MEASURE:
            observed_operation_id, observed_step_index = terminal_observation
            raise DensityMatrixTerminalObservationError(
                observed_operation_id=observed_operation_id,
                observed_step_index=observed_step_index,
                following_operation_id=operation.id,
                following_step_index=step_index,
            )
        if operation.opcode is OpCode.MEASURE:
            if terminal_observation is None:
                terminal_observation = (operation.id, step_index)
        elif operation.opcode is OpCode.RESET:
            density = _apply_reset(density, operation.targets[0])
        else:
            density = _apply_ideal_operation(density, operation)
            gate = _ONE_QUBIT_GATE_BY_OPCODE.get(operation.opcode)
            if gate is not None:
                channel = request.noise_model.channel_for_gate(gate)
                if channel is not None:
                    density = _apply_quantum_channel(
                        density,
                        target=operation.targets[0],
                        channel=channel,
                    )
        _validate_density_matrix(density, qubit_count=circuit.qubit_count)

    return DensityMatrixResult(
        circuit=circuit,
        density_matrix=tuple(tuple(row) for row in density),
    )


def measurement_probabilities(
    density_matrix: DensityMatrix,
    targets: tuple[int, ...],
) -> tuple[float, ...]:
    """Return exact diagonal measurement probabilities in targets-LSB-first order."""

    probabilities = [0.0] * (1 << len(targets))
    for basis_index, probability in enumerate(_matrix_diagonal(density_matrix)):
        outcome = 0
        for outcome_bit, target in enumerate(targets):
            if basis_index & (1 << target):
                outcome |= 1 << outcome_bit
        probabilities[outcome] += probability.real
    return tuple(probabilities)


def _zero_density_matrix(dimension: int) -> list[list[complex]]:
    return [[0j for _ in range(dimension)] for _ in range(dimension)]


def _matrix_diagonal(density_matrix: DensityMatrix | list[list[complex]]) -> tuple[complex, ...]:
    return tuple(density_matrix[index][index] for index in range(len(density_matrix)))


def _apply_ideal_operation(
    density: list[list[complex]],
    operation: Operation,
) -> list[list[complex]]:
    if operation.opcode is OpCode.X:
        return _apply_single_operator(
            density,
            target=operation.targets[0],
            operator=((0j, 1 + 0j), (1 + 0j, 0j)),
        )
    if operation.opcode is OpCode.H:
        scale = 1 / sqrt(2)
        return _apply_single_operator(
            density,
            target=operation.targets[0],
            operator=((scale + 0j, scale + 0j), (scale + 0j, -scale + 0j)),
        )
    if operation.opcode is OpCode.Z:
        return _apply_single_operator(
            density,
            target=operation.targets[0],
            operator=((1 + 0j, 0j), (0j, -1 + 0j)),
        )
    if operation.opcode is OpCode.RX:
        return _apply_single_operator(
            density,
            target=operation.targets[0],
            operator=_rotation_operator(operation.angle_radians, axis="x"),
        )
    if operation.opcode is OpCode.RY:
        return _apply_single_operator(
            density,
            target=operation.targets[0],
            operator=_rotation_operator(operation.angle_radians, axis="y"),
        )
    if operation.opcode is OpCode.RZ:
        return _apply_single_operator(
            density,
            target=operation.targets[0],
            operator=_rotation_operator(operation.angle_radians, axis="z"),
        )
    if operation.opcode is OpCode.CX:
        return _apply_cx(density, control=operation.controls[0], target=operation.targets[0])
    raise ValueError(f"unsupported density-matrix opcode: {operation.opcode}")


def _rotation_operator(angle_radians: float | None, *, axis: str) -> KrausOperator:
    if angle_radians is None:  # pragma: no cover - protected by IR validation
        raise ValueError("rotation operations require angle_radians")
    half_angle = angle_radians / 2
    cosine = cos(half_angle)
    sine = sin(half_angle)
    if axis == "x":
        return ((cosine + 0j, -1j * sine), (-1j * sine, cosine + 0j))
    if axis == "y":
        return ((cosine + 0j, -sine + 0j), (sine + 0j, cosine + 0j))
    if axis == "z":
        return ((cosine - 1j * sine, 0j), (0j, cosine + 1j * sine))
    raise ValueError(f"unsupported rotation axis: {axis}")  # pragma: no cover


def _apply_quantum_channel(
    density: list[list[complex]],
    *,
    target: int,
    channel: QuantumChannel,
) -> list[list[complex]]:
    operators = validate_quantum_channel(channel)
    result = _zero_density_matrix(len(density))
    for operator in operators:
        transformed = _apply_single_operator(density, target=target, operator=operator)
        for row in range(len(density)):
            for column in range(len(density)):
                result[row][column] += transformed[row][column]
    return result


def _apply_single_operator(
    density: list[list[complex]],
    *,
    target: int,
    operator: KrausOperator,
) -> list[list[complex]]:
    """Apply $K\rho K^\dagger$ for a one-qubit operator on an allocated target."""

    dimension = len(density)
    mask = 1 << target
    left_applied = _zero_density_matrix(dimension)
    for base in range(dimension):
        if base & mask:
            continue
        partner = base | mask
        for column in range(dimension):
            zero, one = density[base][column], density[partner][column]
            left_applied[base][column] = operator[0][0] * zero + operator[0][1] * one
            left_applied[partner][column] = operator[1][0] * zero + operator[1][1] * one

    result = _zero_density_matrix(dimension)
    for row in range(dimension):
        for base in range(dimension):
            if base & mask:
                continue
            partner = base | mask
            zero, one = left_applied[row][base], left_applied[row][partner]
            result[row][base] = (
                zero * operator[0][0].conjugate() + one * operator[0][1].conjugate()
            )
            result[row][partner] = (
                zero * operator[1][0].conjugate() + one * operator[1][1].conjugate()
            )
    return result


def _apply_cx(
    density: list[list[complex]],
    *,
    control: int,
    target: int,
) -> list[list[complex]]:
    dimension = len(density)
    control_mask = 1 << control
    target_mask = 1 << target

    def permutation(index: int) -> int:
        return index ^ target_mask if index & control_mask else index

    result = _zero_density_matrix(dimension)
    for row in range(dimension):
        for column in range(dimension):
            result[permutation(row)][permutation(column)] = density[row][column]
    return result


def _apply_reset(density: list[list[complex]], target: int) -> list[list[complex]]:
    """Apply $\rho \mapsto \operatorname{Tr}_q(\rho) \otimes |0\rangle\langle0|$."""

    dimension = len(density)
    mask = 1 << target
    result = _zero_density_matrix(dimension)
    for row in range(dimension):
        if row & mask:
            continue
        for column in range(dimension):
            if column & mask:
                continue
            result[row][column] = density[row][column] + density[row | mask][column | mask]
    return result


def _validate_density_matrix(
    density_matrix: DensityMatrix | list[list[complex]],
    *,
    qubit_count: int,
) -> None:
    if not isinstance(density_matrix, tuple | list):
        raise DensityMatrixInvariantError("density matrix must be a tuple of rows")
    if isinstance(qubit_count, bool) or not isinstance(qubit_count, int) or qubit_count < 0:
        raise DensityMatrixInvariantError("density matrix qubit_count must be non-negative integer")
    dimension = 1 << qubit_count
    if len(density_matrix) != dimension:
        raise DensityMatrixInvariantError("density matrix dimension must equal 2**qubit_count")
    for row in density_matrix:
        if not isinstance(row, tuple | list) or len(row) != dimension:
            raise DensityMatrixInvariantError("density matrix must be square with dimension 2**qubit_count")
        for value in row:
            if not isinstance(value, complex) or not (
                isfinite(value.real) and isfinite(value.imag)
            ):
                raise DensityMatrixInvariantError(
                    "density matrix entries must be finite complex values"
                )
    for row in range(dimension):
        for column in range(dimension):
            if not isclose(
                density_matrix[row][column].real,
                density_matrix[column][row].conjugate().real,
                rel_tol=0.0,
                abs_tol=DENSITY_MATRIX_ABS_TOLERANCE,
            ) or not isclose(
                density_matrix[row][column].imag,
                density_matrix[column][row].conjugate().imag,
                rel_tol=0.0,
                abs_tol=DENSITY_MATRIX_ABS_TOLERANCE,
            ):
                raise DensityMatrixInvariantError("density matrix must be Hermitian")
    trace = sum(density_matrix[index][index] for index in range(dimension))
    if not isclose(trace.real, 1.0, rel_tol=0.0, abs_tol=DENSITY_MATRIX_ABS_TOLERANCE) or not isclose(
        trace.imag,
        0.0,
        rel_tol=0.0,
        abs_tol=DENSITY_MATRIX_ABS_TOLERANCE,
    ):
        raise DensityMatrixInvariantError("density matrix trace must equal one")


__all__ = [
    "DENSITY_MATRIX_ABS_TOLERANCE",
    "DensityMatrix",
    "DensityMatrixExecutionRequest",
    "DensityMatrixInvariantError",
    "DensityMatrixResult",
    "DensityMatrixTerminalObservationError",
    "measurement_probabilities",
    "simulate_density_matrix",
]