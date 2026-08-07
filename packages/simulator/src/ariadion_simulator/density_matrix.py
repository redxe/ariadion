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
    IdleDecoherenceProfile,
    KrausOperator,
    OneQubitGate,
    QuantumChannel,
    validate_executable_noise_model,
    validate_quantum_channel,
)

from .idle_decoherence import IdleDecoherenceEvent, idle_decoherence_channels_for_duration
from .scheduling import ExecutionSchedule, IdleInterval, validate_schedule_for_circuit

DENSITY_MATRIX_ABS_TOLERANCE: Final = 1e-12
"""Absolute tolerance for Hermiticity and trace-one validation."""

DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE: Final = 1e-12
"""Allowed absolute negative pivot error when validating positive semidefiniteness."""

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
    """Explicitly select exact density-matrix execution and its typed noise model.

    ``schedule`` and ``idle_decoherence`` must be supplied together to activate
    idle-decoherence channels. Supplying one without the other leaves idle
    decoherence inactive.
    """

    noise_model: ExecutableNoiseModel = field(default_factory=ExecutableNoiseModel)
    schedule: ExecutionSchedule | None = None
    idle_decoherence: IdleDecoherenceProfile | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.noise_model, ExecutableNoiseModel):
            raise ValueError(
                "density-matrix execution noise_model must be an ExecutableNoiseModel"
            )
        if self.schedule is not None and not isinstance(self.schedule, ExecutionSchedule):
            raise ValueError(
                "density-matrix execution schedule must be an ExecutionSchedule"
            )
        if self.idle_decoherence is not None and not isinstance(
            self.idle_decoherence, IdleDecoherenceProfile
        ):
            raise ValueError(
                "density-matrix execution idle_decoherence must be an IdleDecoherenceProfile"
            )
        if (self.schedule is None) != (self.idle_decoherence is None):
            raise ValueError(
                "density-matrix execution schedule and idle_decoherence must be supplied "
                "together, or both omitted"
            )


@dataclass(frozen=True, slots=True)
class DensityMatrixResult:
    """A final exact mixed state distinct from state-vector amplitudes."""

    circuit: CircuitIR
    density_matrix: DensityMatrix
    idle_decoherence_events: tuple[IdleDecoherenceEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.circuit, CircuitIR):
            raise DensityMatrixInvariantError("density-matrix result circuit must be CircuitIR")
        if not isinstance(self.density_matrix, tuple) or not all(
            isinstance(row, tuple) for row in self.density_matrix
        ):
            raise DensityMatrixInvariantError("density matrix must be an immutable tuple of rows")
        _validate_density_matrix(self.density_matrix, qubit_count=self.circuit.qubit_count)
        if not isinstance(self.idle_decoherence_events, tuple) or not all(
            isinstance(event, IdleDecoherenceEvent) for event in self.idle_decoherence_events
        ):
            raise DensityMatrixInvariantError(
                "density-matrix result idle_decoherence_events must be a tuple of "
                "IdleDecoherenceEvent values"
            )

    @property
    def probabilities(self) -> tuple[float, ...]:
        """Return computational-basis probabilities from the diagonal of $\rho$."""

        return tuple(value.real for value in _matrix_diagonal(self.density_matrix))

    @classmethod
    def _from_trusted_execution(
        cls,
        *,
        circuit: CircuitIR,
        density_matrix: DensityMatrix,
        idle_decoherence_events: tuple[IdleDecoherenceEvent, ...] = (),
    ) -> DensityMatrixResult:
        """Construct a result from trusted simulator evolution without PSD audit.

        This internal path is only for states produced entirely by validated
        unitary and CPTP execution kernels.
        """

        if not isinstance(circuit, CircuitIR):
            raise DensityMatrixInvariantError("density-matrix result circuit must be CircuitIR")
        if not isinstance(density_matrix, tuple) or not all(
            isinstance(row, tuple) for row in density_matrix
        ):
            raise DensityMatrixInvariantError("density matrix must be an immutable tuple of rows")
        _validate_density_matrix_invariants(density_matrix, qubit_count=circuit.qubit_count)
        if not isinstance(idle_decoherence_events, tuple) or not all(
            isinstance(event, IdleDecoherenceEvent) for event in idle_decoherence_events
        ):
            raise DensityMatrixInvariantError(
                "density-matrix result idle_decoherence_events must be a tuple of "
                "IdleDecoherenceEvent values"
            )

        result = object.__new__(cls)
        object.__setattr__(result, "circuit", circuit)
        object.__setattr__(result, "density_matrix", density_matrix)
        object.__setattr__(result, "idle_decoherence_events", idle_decoherence_events)
        return result


def simulate_density_matrix(
    circuit: CircuitIR,
    *,
    execution: DensityMatrixExecutionRequest | None = None,
) -> DensityMatrixResult:
    """Run ideal or explicitly configured noisy exact density-matrix execution.

    Every configured gate channel is resolved through its neutral public gate
    category, then applied after the matching ideal single-qubit operation.
    When both ``schedule`` and ``idle_decoherence`` are supplied in the request,
    idle-decoherence channels are applied to each slot just before the slot's
    next operation, using the ASAP schedule to determine the idle interval.
    Remaining idle time after the last operation is applied at the end.

    Cheap invariant checks (finite entries, Hermiticity, trace-one) are applied
    after each step. The cubic positive-semidefiniteness audit runs once when the
    final ``DensityMatrixResult`` is constructed.
    """

    if not isinstance(circuit, CircuitIR):
        raise ValueError("density-matrix simulation circuit must be CircuitIR")
    request = execution if execution is not None else DensityMatrixExecutionRequest()
    if not isinstance(request, DensityMatrixExecutionRequest):
        raise ValueError(
            "density-matrix simulation execution must be DensityMatrixExecutionRequest"
        )
    validate_executable_noise_model(request.noise_model)
    if request.schedule is not None:
        validate_schedule_for_circuit(circuit, request.schedule)

    dimension = 1 << circuit.qubit_count
    density = _zero_density_matrix(dimension)
    density[0][0] = 1 + 0j
    terminal_observation: tuple[IrOperationId, int] | None = None

    # Idle decoherence tracking: requires both schedule and idle_decoherence.
    apply_idle = request.schedule is not None and request.idle_decoherence is not None
    schedule_lookup: dict[IrOperationId, tuple[float, float]] = {}
    if apply_idle and request.schedule is not None:
        schedule_lookup = {
            op.operation_id: (op.start_ns, op.end_ns)
            for op in request.schedule.scheduled_operations
        }
    slot_last_end: dict[int, float] = {s: 0.0 for s in range(circuit.qubit_count)}
    decoherence_events: list[IdleDecoherenceEvent] = []

    for step_index, operation in enumerate(circuit.operations):
        if terminal_observation is not None and operation.opcode is not OpCode.MEASURE:
            observed_operation_id, observed_step_index = terminal_observation
            raise DensityMatrixTerminalObservationError(
                observed_operation_id=observed_operation_id,
                observed_step_index=observed_step_index,
                following_operation_id=operation.id,
                following_step_index=step_index,
            )

        # Apply idle decoherence for every involved slot before this operation.
        if apply_idle and request.idle_decoherence is not None:
            scheduled = schedule_lookup.get(operation.id)
            if scheduled is not None:
                op_start_ns, op_end_ns = scheduled
                involved_slots = list(operation.targets) + list(operation.controls)
                for slot in involved_slots:
                    idle_start = slot_last_end[slot]
                    idle_end = op_start_ns
                    if idle_end > idle_start:
                        interval = IdleInterval(
                            slot=slot, start_ns=idle_start, end_ns=idle_end
                        )
                        amp_ch, phase_ch, gamma1, p_phi, assumptions, provenance = (
                            idle_decoherence_channels_for_duration(
                                interval.duration_ns, request.idle_decoherence
                            )
                        )
                        if amp_ch is not None:
                            density = _apply_quantum_channel(
                                density, target=slot, channel=amp_ch
                            )
                        if phase_ch is not None:
                            density = _apply_quantum_channel(
                                density, target=slot, channel=phase_ch
                            )
                        decoherence_events.append(
                            IdleDecoherenceEvent(
                                slot=slot,
                                interval=interval,
                                amplitude_damping_probability=gamma1,
                                phase_damping_probability=p_phi,
                                assumptions=assumptions,
                                provenance=provenance,
                            )
                        )
                    slot_last_end[slot] = op_end_ns

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
        # Cheap O(n^2) invariant check after each step; PSD runs once at result construction.
        _validate_density_matrix_invariants(density, qubit_count=circuit.qubit_count)

    # Apply remaining idle time to all slots that have not reached peak_duration_ns.
    if apply_idle and request.schedule is not None and request.idle_decoherence is not None:
        peak = request.schedule.peak_duration_ns
        for slot in range(circuit.qubit_count):
            idle_start = slot_last_end[slot]
            if peak > idle_start:
                interval = IdleInterval(slot=slot, start_ns=idle_start, end_ns=peak)
                amp_ch, phase_ch, gamma1, p_phi, assumptions, provenance = (
                    idle_decoherence_channels_for_duration(
                        interval.duration_ns, request.idle_decoherence
                    )
                )
                if amp_ch is not None:
                    density = _apply_quantum_channel(density, target=slot, channel=amp_ch)
                if phase_ch is not None:
                    density = _apply_quantum_channel(density, target=slot, channel=phase_ch)
                decoherence_events.append(
                    IdleDecoherenceEvent(
                        slot=slot,
                        interval=interval,
                        amplitude_damping_probability=gamma1,
                        phase_damping_probability=p_phi,
                        assumptions=assumptions,
                        provenance=provenance,
                    )
                )

    return DensityMatrixResult._from_trusted_execution(
        circuit=circuit,
        density_matrix=tuple(tuple(row) for row in density),
        idle_decoherence_events=tuple(decoherence_events),
    )


def validate_density_matrix(
    density_matrix: DensityMatrix,
    *,
    qubit_count: int,
) -> None:
    """Explicitly audit a density matrix for all physical invariants.

    Checks finite entries, Hermiticity, trace-one, and positive semidefiniteness.
    This is the full physical audit intended for externally constructed matrices
    and explicit validation requests; it includes the cubic-cost PSD check.

    Raises ``DensityMatrixInvariantError`` if any invariant is violated.
    """
    _validate_density_matrix(density_matrix, qubit_count=qubit_count)


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


def _validate_density_matrix_invariants(
    density_matrix: DensityMatrix | list[list[complex]],
    *,
    qubit_count: int,
) -> None:
    """Cheap O(n^2) invariant check: finite entries, Hermiticity, trace-one.

    Does NOT perform the cubic positive-semidefiniteness audit. Call this after
    each operation in a trusted simulation loop where intermediate states are
    computed by correct unitary and CPTP operations, and call
    ``_validate_density_matrix`` once at the public result boundary.
    """
    if not isinstance(density_matrix, tuple | list):
        raise DensityMatrixInvariantError("density matrix must be a tuple of rows")
    if isinstance(qubit_count, bool) or not isinstance(qubit_count, int) or qubit_count < 0:
        raise DensityMatrixInvariantError("density matrix qubit_count must be non-negative integer")
    dimension = 1 << qubit_count
    if len(density_matrix) != dimension:
        raise DensityMatrixInvariantError("density matrix dimension must equal 2**qubit_count")
    for row in density_matrix:
        if not isinstance(row, tuple | list) or len(row) != dimension:
            raise DensityMatrixInvariantError(
                "density matrix must be square with dimension 2**qubit_count"
            )
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
    if not isclose(
        trace.real,
        1.0,
        rel_tol=0.0,
        abs_tol=DENSITY_MATRIX_ABS_TOLERANCE,
    ) or not isclose(
        trace.imag,
        0.0,
        rel_tol=0.0,
        abs_tol=DENSITY_MATRIX_ABS_TOLERANCE,
    ):
        raise DensityMatrixInvariantError("density matrix trace must equal one")


def _validate_density_matrix(
    density_matrix: DensityMatrix | list[list[complex]],
    *,
    qubit_count: int,
) -> None:
    _validate_density_matrix_invariants(density_matrix, qubit_count=qubit_count)
    dimension = 1 << qubit_count
    _validate_positive_semidefinite(density_matrix, dimension=dimension)


def _validate_positive_semidefinite(
    density_matrix: DensityMatrix | list[list[complex]],
    *,
    dimension: int,
) -> None:
    """Validate $\rho \succeq 0$ using diagonal-pivoted Cholesky elimination.

    A Hermitian positive semidefinite matrix has no materially negative pivot in
    this decomposition. Diagonal pivoting makes the check robust for semidefinite
    matrices; a near-zero pivot may only have near-zero remaining couplings.
    """

    remaining = [
        [complex(density_matrix[row][column]) for column in range(dimension)]
        for row in range(dimension)
    ]
    tolerance = DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE

    for pivot_index in range(dimension):
        pivot_row = max(
            range(pivot_index, dimension),
            key=lambda index: remaining[index][index].real,
        )
        if pivot_row != pivot_index:
            remaining[pivot_index], remaining[pivot_row] = (
                remaining[pivot_row],
                remaining[pivot_index],
            )
            for row in range(dimension):
                remaining[row][pivot_index], remaining[row][pivot_row] = (
                    remaining[row][pivot_row],
                    remaining[row][pivot_index],
                )

        pivot = remaining[pivot_index][pivot_index].real
        if pivot < -tolerance:
            raise DensityMatrixInvariantError(
                "density matrix must be positive semidefinite within "
                f"{DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE}"
            )
        if pivot <= tolerance:
            if any(
                abs(remaining[row][pivot_index]) > tolerance
                for row in range(pivot_index + 1, dimension)
            ):
                raise DensityMatrixInvariantError(
                    "density matrix must be positive semidefinite within "
                    f"{DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE}"
                )
            continue

        for row in range(pivot_index + 1, dimension):
            factor = remaining[row][pivot_index] / pivot
            for column in range(pivot_index + 1, dimension):
                remaining[row][column] -= factor * remaining[pivot_index][column]


__all__ = [
    "DENSITY_MATRIX_ABS_TOLERANCE",
    "DENSITY_MATRIX_POSITIVITY_ABS_TOLERANCE",
    "DensityMatrix",
    "DensityMatrixExecutionRequest",
    "DensityMatrixInvariantError",
    "DensityMatrixResult",
    "DensityMatrixTerminalObservationError",
    "measurement_probabilities",
    "simulate_density_matrix",
    "validate_density_matrix",
]