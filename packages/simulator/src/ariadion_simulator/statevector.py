from __future__ import annotations

from dataclasses import dataclass
from math import isclose, sqrt
from typing import Final, Generic, Protocol, TypeVar, overload

from ariadion_ir import CircuitIR, IrOperationId, OpCode, Operation


EXPECTED_STATE_VECTOR_NORM: Final = 1.0
STATE_VECTOR_NORM_ABS_TOLERANCE: Final = 1e-12

_TraceArtifact = TypeVar("_TraceArtifact", covariant=True)


class _TraceCaptureRequest(Protocol[_TraceArtifact]):
    """Structural boundary for runtime-owned trace capture options."""

    enabled: bool

    def build_execution_trace(
        self,
        result: SimulationResult,
        captured_trace: SimulationTrace,
    ) -> _TraceArtifact: ...


@dataclass(frozen=True, slots=True)
class SimulationResult:
    circuit: CircuitIR
    amplitudes: tuple[complex, ...]

    @property
    def probabilities(self) -> tuple[float, ...]:
        return tuple(abs(value) ** 2 for value in self.amplitudes)


@dataclass(frozen=True, slots=True)
class SimulationTraceStep:
    """Raw immutable state transition captured by the reference simulator."""

    index: int
    operation: Operation
    before_amplitudes: tuple[complex, ...]
    after_amplitudes: tuple[complex, ...]
    measurement_probabilities: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class SimulationTrace:
    """Backend-neutral raw capture data projected to runtime contracts upstream."""

    initial_amplitudes: tuple[complex, ...]
    steps: tuple[SimulationTraceStep, ...]


@dataclass(frozen=True, slots=True)
class SimulationExecution(Generic[_TraceArtifact]):
    """A final simulation result and an optional projected execution trace."""

    result: SimulationResult
    trace: _TraceArtifact | None


class SimulationNormError(RuntimeError):
    """Raised when a unitary operation violates state-vector normalization."""

    def __init__(
        self,
        *,
        operation_id: IrOperationId,
        step_index: int,
        observed_norm: float,
        expected_norm: float,
        tolerance: float,
    ) -> None:
        self.operation_id = operation_id
        self.step_index = step_index
        self.observed_norm = observed_norm
        self.expected_norm = expected_norm
        self.tolerance = tolerance
        super().__init__(
            "state-vector norm invariant failed "
            f"at step {step_index} for operation {operation_id}: "
            f"observed {observed_norm}, expected {expected_norm} "
            f"within {tolerance}"
        )


@overload
def simulate(circuit: CircuitIR) -> SimulationResult: ...


@overload
def simulate(
    circuit: CircuitIR,
    *,
    trace: _TraceCaptureRequest[_TraceArtifact],
) -> SimulationExecution[_TraceArtifact]: ...


def simulate(
    circuit: CircuitIR,
    *,
    trace: _TraceCaptureRequest[object] | None = None,
) -> SimulationResult | SimulationExecution[object]:
    """Run a deterministic state-vector simulation with optional trace capture.

    The legacy no-keyword form returns ``SimulationResult``. Supplying a trace
    request returns ``SimulationExecution`` regardless of whether capture is
    enabled, avoiding a return-type change based on the option value itself.
    """

    captured_execution = _simulate_execution(
        circuit,
        retain_trace=trace is not None and trace.enabled,
    )
    if trace is None:
        return captured_execution.result
    if captured_execution.trace is None:
        return SimulationExecution(captured_execution.result, None)
    return SimulationExecution(
        captured_execution.result,
        trace.build_execution_trace(captured_execution.result, captured_execution.trace),
    )


def _simulate_execution(
    circuit: CircuitIR,
    *,
    retain_trace: bool,
) -> SimulationExecution[SimulationTrace]:
    size = 1 << circuit.qubit_count
    state = [0j] * size
    state[0] = 1 + 0j
    initial_amplitudes = tuple(state) if retain_trace else None
    steps: list[SimulationTraceStep] | None = [] if retain_trace else None

    for index, operation in enumerate(circuit.operations):
        before_amplitudes = tuple(state) if retain_trace else None
        state = apply_operation(state, operation)
        if operation.opcode is not OpCode.MEASURE:
            _validate_state_norm(state, operation=operation, step_index=index)

        if steps is not None:
            assert before_amplitudes is not None
            measurement_probabilities = (
                _measurement_probabilities(state, operation.targets)
                if operation.opcode is OpCode.MEASURE
                else None
            )
            steps.append(
                SimulationTraceStep(
                    index=index,
                    operation=operation,
                    before_amplitudes=before_amplitudes,
                    after_amplitudes=tuple(state),
                    measurement_probabilities=measurement_probabilities,
                )
            )

    result = SimulationResult(circuit, tuple(state))
    captured_trace = None
    if steps is not None:
        assert initial_amplitudes is not None
        captured_trace = SimulationTrace(initial_amplitudes, tuple(steps))
    return SimulationExecution(result, captured_trace)


def apply_operation(state: list[complex], operation: Operation) -> list[complex]:
    """Deterministically mutate ``state`` for one IR operation without tracing."""

    if operation.opcode is OpCode.X:
        _apply_single(state, operation.targets[0], 0j, 1 + 0j, 1 + 0j, 0j)
    elif operation.opcode is OpCode.H:
        scale = 1 / sqrt(2)
        _apply_single(state, operation.targets[0], scale, scale, scale, -scale)
    elif operation.opcode is OpCode.Z:
        _apply_single(state, operation.targets[0], 1 + 0j, 0j, 0j, -1 + 0j)
    elif operation.opcode is OpCode.CX:
        _apply_cx(state, operation.controls[0], operation.targets[0])
    elif operation.opcode is OpCode.MEASURE:
        # The reference simulator keeps the full state. Measurement sampling and
        # collapse will be introduced with explicit runtime policies.
        return state
    else:  # pragma: no cover - protects future enum expansion
        raise ValueError(f"unsupported opcode: {operation.opcode}")
    return state


def _validate_state_norm(
    state: list[complex],
    *,
    operation: Operation,
    step_index: int,
) -> None:
    observed_norm = sum(abs(amplitude) ** 2 for amplitude in state)
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


def _measurement_probabilities(
    state: list[complex],
    targets: tuple[int, ...],
) -> tuple[float, ...]:
    """Return exact probabilities with ``targets[i]`` mapped to outcome bit ``i``."""

    probabilities = [0.0] * (1 << len(targets))
    for basis_index, amplitude in enumerate(state):
        outcome = 0
        for outcome_bit, target in enumerate(targets):
            if basis_index & (1 << target):
                outcome |= 1 << outcome_bit
        probabilities[outcome] += abs(amplitude) ** 2
    return tuple(probabilities)


def _apply_single(
    state: list[complex],
    target: int,
    m00: complex,
    m01: complex,
    m10: complex,
    m11: complex,
) -> None:
    mask = 1 << target
    for base in range(len(state)):
        if base & mask:
            continue
        partner = base | mask
        zero, one = state[base], state[partner]
        state[base] = m00 * zero + m01 * one
        state[partner] = m10 * zero + m11 * one


def _apply_cx(state: list[complex], control: int, target: int) -> None:
    control_mask = 1 << control
    target_mask = 1 << target
    for base in range(len(state)):
        if not (base & control_mask) or (base & target_mask):
            continue
        partner = base | target_mask
        state[base], state[partner] = state[partner], state[base]
