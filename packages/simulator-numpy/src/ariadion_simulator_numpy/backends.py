"""Optional NumPy CPU kernels that preserve Ariadion reference semantics.

The backend holds arrays only while executing. Its public results are the existing
immutable tuple-based Ariadion result types, so neither backend capabilities nor
runtime-facing results acquire a NumPy array dependency.
"""

from __future__ import annotations

from math import cos, isclose, sin, sqrt
from typing import Final

import numpy as np
from ariadion_ir import CircuitIR, IrOperationId, OpCode, Operation
from ariadion_noise import (
    OneQubitGate,
    QuantumChannel,
    validate_executable_noise_model,
    validate_quantum_channel,
)
from ariadion_simulator import (
    EXPECTED_STATE_VECTOR_NORM,
    STATE_VECTOR_NORM_ABS_TOLERANCE,
    DensityMatrixExecutionRequest,
    DensityMatrixResult,
    DensityMatrixTerminalObservationError,
    GateNoiseApplicationEvent,
    ExactResetUnsupportedError,
    ExactTerminalObservationError,
    IdleDecoherenceEvent,
    IdleInterval,
    OperatorStructure,
    SimulationCapabilities,
    SimulationNormError,
    SimulationPlan,
    SimulationQuery,
    SimulationResult,
    StateRepresentation,
    build_simulation_plan,
    idle_decoherence_channels_for_duration,
    kernel_metadata_for_operation,
    validate_schedule_for_circuit,
)
from ariadion_noise import NoiseFeature

NUMPY_COMPLEX_DTYPE: Final = np.dtype(np.complex128)
"""Fixed precision for reference parity; mixed precision is intentionally unsupported."""

_ONE_QUBIT_GATE_BY_OPCODE: Final = {
    OpCode.X: OneQubitGate.X,
    OpCode.H: OneQubitGate.H,
    OpCode.Z: OneQubitGate.Z,
    OpCode.RX: OneQubitGate.RX,
    OpCode.RY: OneQubitGate.RY,
    OpCode.RZ: OneQubitGate.RZ,
}
_NUMPY_STATE_VECTOR_CAPABILITIES: Final = SimulationCapabilities(
    representations=(StateRepresentation.STATE_VECTOR,),
    queries=(SimulationQuery.FULL_STATE, SimulationQuery.PROBABILITIES),
    noise_features=(),
    supports_reset=False,
    supports_sampling=False,
)
_NUMPY_DENSITY_MATRIX_CAPABILITIES: Final = SimulationCapabilities(
    representations=(StateRepresentation.DENSITY_MATRIX,),
    queries=(SimulationQuery.FULL_STATE, SimulationQuery.PROBABILITIES),
    noise_features=(NoiseFeature.GATE_CHANNELS, NoiseFeature.IDLE_DECOHERENCE),
    supports_reset=True,
    supports_sampling=False,
)


class NumpyStateVectorBackend:
    """CPU exact-state-vector execution using local NumPy ``complex128`` kernels."""

    backend_id: Final = "numpy-cpu-state-vector"
    representation: Final = StateRepresentation.STATE_VECTOR
    capabilities: Final = _NUMPY_STATE_VECTOR_CAPABILITIES

    def plan(
        self,
        circuit: CircuitIR,
        *,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationPlan:
        return build_simulation_plan(
            backend_id=self.backend_id,
            capabilities=self.capabilities,
            representation=self.representation,
            query=query,
            reasons=(
                "caller explicitly selected the NumPy CPU state-vector backend",
                "local complex128 tensor, permutation, and diagonal kernels only",
                "no full-system gate matrix is constructed",
            ),
        )

    def execute(
        self,
        circuit: CircuitIR,
        *,
        options: None = None,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationResult:
        if not isinstance(circuit, CircuitIR):
            raise ValueError("NumPy state-vector circuit must be CircuitIR")
        if options is not None:
            raise ValueError("numpy-cpu-state-vector does not accept execution options")
        self.plan(circuit, query=query)

        state = np.zeros(1 << circuit.qubit_count, dtype=NUMPY_COMPLEX_DTYPE)
        state[0] = 1
        terminal_observation: tuple[IrOperationId, int] | None = None
        for step_index, operation in enumerate(circuit.operations):
            if operation.opcode is OpCode.RESET:
                raise ExactResetUnsupportedError(
                    operation_id=operation.id,
                    step_index=step_index,
                )
            if terminal_observation is not None and operation.opcode is not OpCode.MEASURE:
                observed_operation_id, observed_step_index = terminal_observation
                raise ExactTerminalObservationError(
                    observed_operation_id=observed_operation_id,
                    observed_step_index=observed_step_index,
                    following_operation_id=operation.id,
                    following_step_index=step_index,
                )
            if operation.opcode is OpCode.MEASURE:
                if terminal_observation is None:
                    terminal_observation = (operation.id, step_index)
                continue
            state = _apply_statevector_operation(
                state,
                operation=operation,
                qubit_count=circuit.qubit_count,
            )
            _validate_state_norm(state, operation=operation, step_index=step_index)
        return SimulationResult(circuit, tuple(complex(value) for value in state))


class NumpyDensityMatrixBackend:
    """CPU exact-density execution using local NumPy ``complex128`` kernels."""

    backend_id: Final = "numpy-cpu-density-matrix"
    representation: Final = StateRepresentation.DENSITY_MATRIX
    capabilities: Final = _NUMPY_DENSITY_MATRIX_CAPABILITIES

    def plan(
        self,
        circuit: CircuitIR,
        *,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> SimulationPlan:
        return build_simulation_plan(
            backend_id=self.backend_id,
            capabilities=self.capabilities,
            representation=self.representation,
            query=query,
            reasons=(
                "caller explicitly selected the NumPy CPU density-matrix backend",
                "local complex128 U-rho-U-dagger and Kraus kernels only",
                "no full-system gate matrix or superoperator is constructed",
            ),
        )

    def execute(
        self,
        circuit: CircuitIR,
        *,
        options: DensityMatrixExecutionRequest | None = None,
        query: SimulationQuery = SimulationQuery.FULL_STATE,
    ) -> DensityMatrixResult:
        if not isinstance(circuit, CircuitIR):
            raise ValueError("NumPy density-matrix circuit must be CircuitIR")
        if options is not None and not isinstance(options, DensityMatrixExecutionRequest):
            raise ValueError(
                "NumPy density-matrix options must be DensityMatrixExecutionRequest"
            )
        self.plan(circuit, query=query)
        request = options if options is not None else DensityMatrixExecutionRequest()
        validate_executable_noise_model(request.noise_model)
        if request.schedule is not None:
            validate_schedule_for_circuit(circuit, request.schedule)

        dimension = 1 << circuit.qubit_count
        density = np.zeros((dimension, dimension), dtype=NUMPY_COMPLEX_DTYPE)
        density[0, 0] = 1
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
        gate_noise_events: list[GateNoiseApplicationEvent] = []

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
                                    density,
                                    target=slot,
                                    qubit_count=circuit.qubit_count,
                                    channel=amp_ch,
                                )
                            if phase_ch is not None:
                                density = _apply_quantum_channel(
                                    density,
                                    target=slot,
                                    qubit_count=circuit.qubit_count,
                                    channel=phase_ch,
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
                continue
            if operation.opcode is OpCode.RESET:
                density = _apply_density_reset(
                    density,
                    target=operation.targets[0],
                )
                continue

            density = _apply_density_ideal_operation(
                density,
                operation=operation,
                qubit_count=circuit.qubit_count,
            )
            gate = _ONE_QUBIT_GATE_BY_OPCODE.get(operation.opcode)
            channel = request.noise_model.channel_for_gate(gate) if gate is not None else None
            if channel is not None:
                metadata = kernel_metadata_for_operation(
                    operation,
                    has_quantum_channel=True,
                )
                if (
                    metadata[-1].structure is not OperatorStructure.KRAUS_CHANNEL
                ):  # pragma: no cover
                    raise RuntimeError("post-gate channel metadata must be a Kraus channel")
                density = _apply_quantum_channel(
                    density,
                    target=operation.targets[0],
                    qubit_count=circuit.qubit_count,
                    channel=channel,
                )
                gate_noise_events.append(
                    GateNoiseApplicationEvent(
                        operation_id=operation.id,
                        target_slot=operation.targets[0],
                        gate=gate,
                        channel=channel,
                        application_order=len(gate_noise_events),
                    )
                )

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
                        density = _apply_quantum_channel(
                            density,
                            target=slot,
                            qubit_count=circuit.qubit_count,
                            channel=amp_ch,
                        )
                    if phase_ch is not None:
                        density = _apply_quantum_channel(
                            density,
                            target=slot,
                            qubit_count=circuit.qubit_count,
                            channel=phase_ch,
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

        matrix = tuple(
            tuple(complex(value) for value in row)
            for row in density
        )
        return DensityMatrixResult._from_trusted_execution(
            circuit=circuit,
            density_matrix=matrix,
            idle_decoherence_events=tuple(decoherence_events),
            gate_noise_events=tuple(gate_noise_events),
        )


def _apply_statevector_operation(
    state: np.ndarray,
    *,
    operation: Operation,
    qubit_count: int,
) -> np.ndarray:
    metadata = kernel_metadata_for_operation(operation)
    if len(metadata) != 1:  # pragma: no cover - observations are handled by the caller
        raise ValueError("NumPy state-vector operations require one evolution kernel")
    structure = metadata[0].structure
    target = operation.targets[0]
    if structure is OperatorStructure.PERMUTATION:
        return _apply_x_statevector(state, target=target)
    if structure is OperatorStructure.DIAGONAL:
        return _apply_diagonal_statevector(
            state,
            target=target,
            diagonal=_diagonal_for_operation(operation),
        )
    if structure is OperatorStructure.LOCAL_DENSE:
        return _apply_local_dense_statevector(
            state,
            target=target,
            qubit_count=qubit_count,
            operator=_operator_for_operation(operation),
        )
    if structure is OperatorStructure.CONTROLLED_PERMUTATION:
        return _apply_cx_statevector(
            state,
            control=operation.controls[0],
            target=target,
        )
    raise ValueError(f"unsupported NumPy state-vector kernel structure: {structure}")


def _apply_density_ideal_operation(
    density: np.ndarray,
    *,
    operation: Operation,
    qubit_count: int,
) -> np.ndarray:
    metadata = kernel_metadata_for_operation(operation)
    if len(metadata) != 1:  # pragma: no cover - observations are handled by the caller
        raise ValueError("NumPy density operations require one evolution kernel")
    structure = metadata[0].structure
    if structure is OperatorStructure.CONTROLLED_PERMUTATION:
        return _apply_cx_density(
            density,
            control=operation.controls[0],
            target=operation.targets[0],
        )
    if structure in {
        OperatorStructure.PERMUTATION,
        OperatorStructure.DIAGONAL,
        OperatorStructure.LOCAL_DENSE,
    }:
        return _apply_local_density_operator(
            density,
            target=operation.targets[0],
            qubit_count=qubit_count,
            operator=_operator_for_operation(operation),
        )
    raise ValueError(f"unsupported NumPy density kernel structure: {structure}")


def _operator_for_operation(operation: Operation) -> np.ndarray:
    if operation.opcode is OpCode.X:
        return np.asarray(((0, 1), (1, 0)), dtype=NUMPY_COMPLEX_DTYPE)
    if operation.opcode is OpCode.H:
        scale = 1 / sqrt(2)
        return np.asarray(((scale, scale), (scale, -scale)), dtype=NUMPY_COMPLEX_DTYPE)
    if operation.opcode is OpCode.Z:
        return np.asarray(((1, 0), (0, -1)), dtype=NUMPY_COMPLEX_DTYPE)
    if operation.opcode is OpCode.RX:
        return _rotation_operator(operation.angle_radians, axis="x")
    if operation.opcode is OpCode.RY:
        return _rotation_operator(operation.angle_radians, axis="y")
    if operation.opcode is OpCode.RZ:
        return _rotation_operator(operation.angle_radians, axis="z")
    raise ValueError(f"operation has no local NumPy operator: {operation.opcode}")


def _diagonal_for_operation(operation: Operation) -> tuple[complex, complex]:
    operator = _operator_for_operation(operation)
    return complex(operator[0, 0]), complex(operator[1, 1])


def _rotation_operator(angle_radians: float | None, *, axis: str) -> np.ndarray:
    if angle_radians is None:  # pragma: no cover - protected by IR validation
        raise ValueError("rotation operations require angle_radians")
    half_angle = angle_radians / 2
    cosine = cos(half_angle)
    sine = sin(half_angle)
    if axis == "x":
        entries = ((cosine, -1j * sine), (-1j * sine, cosine))
    elif axis == "y":
        entries = ((cosine, -sine), (sine, cosine))
    elif axis == "z":
        entries = ((cosine - 1j * sine, 0), (0, cosine + 1j * sine))
    else:  # pragma: no cover - only fixed axes are passed above
        raise ValueError(f"unsupported rotation axis: {axis}")
    return np.asarray(entries, dtype=NUMPY_COMPLEX_DTYPE)


def _apply_x_statevector(state: np.ndarray, *, target: int) -> np.ndarray:
    indexes = np.arange(state.size)
    mask = 1 << target
    zero_indexes = indexes[(indexes & mask) == 0]
    one_indexes = zero_indexes | mask
    result = state.copy()
    result[zero_indexes] = state[one_indexes]
    result[one_indexes] = state[zero_indexes]
    return result


def _apply_diagonal_statevector(
    state: np.ndarray,
    *,
    target: int,
    diagonal: tuple[complex, complex],
) -> np.ndarray:
    indexes = np.arange(state.size)
    mask = 1 << target
    result = state.copy()
    one_indexes = (indexes & mask) != 0
    result[~one_indexes] *= diagonal[0]
    result[one_indexes] *= diagonal[1]
    return result


def _apply_local_dense_statevector(
    state: np.ndarray,
    *,
    target: int,
    qubit_count: int,
    operator: np.ndarray,
) -> np.ndarray:
    """Apply a 2x2 matrix along one state-tensor axis, never a global gate matrix."""

    axis = qubit_count - 1 - target
    tensor = state.reshape((2,) * qubit_count)
    moved = np.moveaxis(tensor, axis, 0)
    transformed = np.einsum("ab,b...->a...", operator, moved, optimize=True)
    return np.ascontiguousarray(np.moveaxis(transformed, 0, axis).reshape(-1))


def _apply_cx_statevector(state: np.ndarray, *, control: int, target: int) -> np.ndarray:
    indexes = np.arange(state.size)
    control_mask = 1 << control
    target_mask = 1 << target
    source_indexes = indexes[((indexes & control_mask) != 0) & ((indexes & target_mask) == 0)]
    partner_indexes = source_indexes | target_mask
    result = state.copy()
    result[source_indexes] = state[partner_indexes]
    result[partner_indexes] = state[source_indexes]
    return result


def _apply_local_density_operator(
    density: np.ndarray,
    *,
    target: int,
    qubit_count: int,
    operator: np.ndarray,
) -> np.ndarray:
    """Apply local $K\rho K^\dagger$ without a superoperator.

    Reshape stores each basis index most-significant-bit first, so allocated slot
    ``target`` is row axis ``qubit_count - 1 - target`` and the corresponding
    column axis is offset by ``qubit_count``. This preserves Ariadion's
    least-significant-bit allocated-slot convention.
    """

    row_axis = qubit_count - 1 - target
    column_axis = (2 * qubit_count) - 1 - target
    tensor = density.reshape((2,) * (2 * qubit_count))
    rows_first = np.moveaxis(tensor, row_axis, 0)
    left_applied = np.einsum("ab,b...->a...", operator, rows_first, optimize=True)
    left_restored = np.moveaxis(left_applied, 0, row_axis)
    columns_last = np.moveaxis(left_restored, column_axis, -1)
    right_applied = np.einsum(
        "...b,bc->...c",
        columns_last,
        operator.conjugate().T,
        optimize=True,
    )
    return np.ascontiguousarray(
        np.moveaxis(right_applied, -1, column_axis).reshape(density.shape)
    )


def _apply_cx_density(density: np.ndarray, *, control: int, target: int) -> np.ndarray:
    indexes = np.arange(density.shape[0])
    control_mask = 1 << control
    target_mask = 1 << target
    permutation = np.where((indexes & control_mask) != 0, indexes ^ target_mask, indexes)
    return density[np.ix_(permutation, permutation)].copy()


def _apply_quantum_channel(
    density: np.ndarray,
    *,
    target: int,
    qubit_count: int,
    channel: QuantumChannel,
) -> np.ndarray:
    result = np.zeros_like(density, dtype=NUMPY_COMPLEX_DTYPE)
    for kraus_operator in validate_quantum_channel(channel):
        result += _apply_local_density_operator(
            density,
            target=target,
            qubit_count=qubit_count,
            operator=np.asarray(kraus_operator, dtype=NUMPY_COMPLEX_DTYPE),
        )
    return result


def _apply_density_reset(density: np.ndarray, *, target: int) -> np.ndarray:
    indexes = np.arange(density.shape[0])
    mask = 1 << target
    zero_indexes = indexes[(indexes & mask) == 0]
    one_indexes = zero_indexes | mask
    result = np.zeros_like(density, dtype=NUMPY_COMPLEX_DTYPE)
    result[np.ix_(zero_indexes, zero_indexes)] = (
        density[np.ix_(zero_indexes, zero_indexes)]
        + density[np.ix_(one_indexes, one_indexes)]
    )
    return result


def _validate_state_norm(
    state: np.ndarray,
    *,
    operation: Operation,
    step_index: int,
) -> None:
    observed_norm = float(np.vdot(state, state).real)
    if not isclose(
        observed_norm,
        EXPECTED_STATE_VECTOR_NORM,
        rel_tol=0.0,
        abs_tol=STATE_VECTOR_NORM_ABS_TOLERANCE,
    ):
        raise SimulationNormError(
            operation_id=operation.id,
            step_index=step_index,
            observed_norm=observed_norm,
            expected_norm=EXPECTED_STATE_VECTOR_NORM,
            tolerance=STATE_VECTOR_NORM_ABS_TOLERANCE,
        )


__all__ = [
    "NUMPY_COMPLEX_DTYPE",
    "NumpyDensityMatrixBackend",
    "NumpyStateVectorBackend",
]
