from __future__ import annotations

from dataclasses import dataclass
from math import cos, isclose, sin, sqrt
from random import Random
from typing import Final, Generic, Protocol, TypeVar, overload

from ariadion_ir import CircuitIR, IrOperationId, OpCode, Operation


EXPECTED_STATE_VECTOR_NORM: Final = 1.0
STATE_VECTOR_NORM_ABS_TOLERANCE: Final = 1e-12

_TraceArtifact = TypeVar("_TraceArtifact", covariant=True)
_SimulationArtifact = TypeVar("_SimulationArtifact", covariant=True)


class _TraceCaptureRequest(Protocol[_TraceArtifact]):
    """Structural boundary for runtime-owned trace capture options."""

    enabled: bool

    def build_execution_trace(
        self,
        result: SimulationResult,
        captured_trace: SimulationTrace,
        *,
        sampled: bool = False,
        seed: int | None = None,
    ) -> _TraceArtifact: ...


@dataclass(frozen=True, slots=True)
class SimulationResult:
    circuit: CircuitIR
    amplitudes: tuple[complex, ...]

    @property
    def probabilities(self) -> tuple[float, ...]:
        return tuple(abs(value) ** 2 for value in self.amplitudes)


@dataclass(frozen=True, slots=True)
class SampledExecutionRequest:
    """Configure independent sampled state-vector trajectories."""

    shots: int
    seed: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.shots, bool) or not isinstance(self.shots, int) or self.shots < 1:
            raise ValueError("sampled execution shots must be an integer of at least one")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("sampled execution seed must be an integer or None")


@dataclass(frozen=True, slots=True)
class SimulationMeasurementOutcome:
    """One sampled user-visible measurement outcome in target order."""

    operation_id: IrOperationId
    targets: tuple[int, ...]
    outcome: tuple[int, ...]

    def __post_init__(self) -> None:
        _require_nonempty_operation_id(
            self.operation_id,
            label="sampled measurement operation ID",
        )
        if not isinstance(self.targets, tuple) or not self.targets:
            raise ValueError("sampled measurement targets must be a non-empty tuple")
        if any(
            isinstance(target, bool) or not isinstance(target, int) or target < 0
            for target in self.targets
        ):
            raise ValueError("sampled measurement targets must be non-negative integers")
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("sampled measurement targets must be unique")
        if not isinstance(self.outcome, tuple) or len(self.outcome) != len(self.targets):
            raise ValueError("sampled measurement outcome must contain one bit per target")
        if any(
            isinstance(bit, bool) or not isinstance(bit, int) or bit not in {0, 1}
            for bit in self.outcome
        ):
            raise ValueError("sampled measurement outcome must contain only bits")


@dataclass(frozen=True, slots=True)
class SimulationResetEvent:
    """One internal sampled measurement and conditional correction implementing RESET."""

    operation_id: IrOperationId
    target: int
    sampled_internal_outcome: int

    def __post_init__(self) -> None:
        _require_nonempty_operation_id(self.operation_id, label="sampled reset operation ID")
        if isinstance(self.target, bool) or not isinstance(self.target, int) or self.target < 0:
            raise ValueError("sampled reset target must be a non-negative integer")
        if (
            isinstance(self.sampled_internal_outcome, bool)
            or not isinstance(self.sampled_internal_outcome, int)
            or self.sampled_internal_outcome not in {0, 1}
        ):
            raise ValueError("sampled reset internal outcome must be zero or one")


@dataclass(frozen=True, slots=True)
class SampledSimulationShot:
    """One independently initialized and fully executed sampled trajectory."""

    index: int
    result: SimulationResult
    measurement_outcomes: tuple[SimulationMeasurementOutcome, ...]
    reset_events: tuple[SimulationResetEvent, ...]

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError("sampled simulation shot index must be a non-negative integer")
        if not isinstance(self.result, SimulationResult):
            raise ValueError("sampled simulation shot result must be SimulationResult")
        if not isinstance(self.measurement_outcomes, tuple) or not all(
            isinstance(outcome, SimulationMeasurementOutcome)
            for outcome in self.measurement_outcomes
        ):
            raise ValueError(
                "sampled simulation shot measurement_outcomes must contain "
                "SimulationMeasurementOutcome values"
            )
        if not isinstance(self.reset_events, tuple) or not all(
            isinstance(event, SimulationResetEvent) for event in self.reset_events
        ):
            raise ValueError(
                "sampled simulation shot reset_events must contain SimulationResetEvent values"
            )


@dataclass(frozen=True, slots=True)
class SampledSimulationResult:
    """Independent sampled trajectories for one circuit and private RNG seed."""

    circuit: CircuitIR
    shots: tuple[SampledSimulationShot, ...]
    seed: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.circuit, CircuitIR):
            raise ValueError("sampled simulation circuit must be CircuitIR")
        if not isinstance(self.shots, tuple) or not self.shots:
            raise ValueError("sampled simulation shots must be a non-empty tuple")
        if not all(isinstance(shot, SampledSimulationShot) for shot in self.shots):
            raise ValueError("sampled simulation shots must contain SampledSimulationShot values")
        if tuple(shot.index for shot in self.shots) != tuple(range(len(self.shots))):
            raise ValueError("sampled simulation shot indexes must be contiguous from zero")
        if any(shot.result.circuit != self.circuit for shot in self.shots):
            raise ValueError("sampled simulation shot circuits must match the sampled circuit")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("sampled simulation seed must be an integer or None")


@dataclass(frozen=True, slots=True)
class SimulationTraceStep:
    """Raw immutable state transition captured by the reference simulator."""

    index: int
    operation: Operation
    before_amplitudes: tuple[complex, ...]
    after_amplitudes: tuple[complex, ...]
    measurement_probabilities: tuple[float, ...] | None = None
    measurement_outcome: tuple[int, ...] | None = None
    reset_event: SimulationResetEvent | None = None

    def __post_init__(self) -> None:
        if (
            self.measurement_probabilities is not None
            and self.measurement_outcome is not None
        ):
            raise ValueError(
                "simulation trace steps cannot combine exact measurement probabilities "
                "with a sampled measurement outcome"
            )
        if (
            self.measurement_probabilities is not None
            and self.operation.opcode is not OpCode.MEASURE
        ):
            raise ValueError("exact measurement probabilities require a MEASURE operation")
        if self.measurement_outcome is not None and self.operation.opcode is not OpCode.MEASURE:
            raise ValueError("sampled measurement outcomes require a MEASURE operation")
        if self.measurement_outcome is not None:
            SimulationMeasurementOutcome(
                operation_id=self.operation.id,
                targets=self.operation.targets,
                outcome=self.measurement_outcome,
            )
        if self.reset_event is not None:
            if not isinstance(self.reset_event, SimulationResetEvent):
                raise ValueError("simulation trace reset_event must be SimulationResetEvent")
            if self.operation.opcode is not OpCode.RESET:
                raise ValueError("simulation trace reset events require a RESET operation")
            if self.reset_event.operation_id != self.operation.id:
                raise ValueError("simulation trace reset event operation ID must match")
            if self.operation.targets != (self.reset_event.target,):
                raise ValueError("simulation trace reset event target must match")
        if self.measurement_outcome is not None and self.reset_event is not None:
            raise ValueError("simulation trace steps cannot combine measurement and reset evidence")


@dataclass(frozen=True, slots=True)
class SimulationTrace:
    """Backend-neutral raw capture data projected to runtime contracts upstream."""

    initial_amplitudes: tuple[complex, ...]
    steps: tuple[SimulationTraceStep, ...]


@dataclass(frozen=True, slots=True)
class SimulationExecution(Generic[_SimulationArtifact, _TraceArtifact]):
    """A final simulation result and an optional projected execution trace."""

    result: _SimulationArtifact
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


class ExactTerminalObservationError(ValueError):
    """Raised when exact state-vector execution encounters a non-terminal observation."""

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
            f"{self.code}: exact state-vector execution supports terminal observations only "
            f"(observation at step {observed_step_index}, later operation at step "
            f"{following_step_index})"
        )


class ExactResetUnsupportedError(ValueError):
    """Raised because an entangled reset channel has no exact pure-state-vector form."""

    code: Final = "A203"

    def __init__(
        self,
        *,
        operation_id: IrOperationId,
        step_index: int | None = None,
    ) -> None:
        self.operation_id = operation_id
        self.step_index = step_index
        location = f" at step {step_index}" if step_index is not None else ""
        super().__init__(
            f"{self.code}: exact state-vector execution does not support general reset"
            f"{location} (operation {operation_id})"
        )


class SampledTraceShotCountError(ValueError):
    """Raised when a single linear trace is requested for multiple trajectories."""

    code: Final = "A204"

    def __init__(self, shots: int) -> None:
        self.shots = shots
        super().__init__(
            f"{self.code}: sampled trace capture currently supports exactly one shot "
            f"(received {shots})"
        )


@overload
def simulate(circuit: CircuitIR) -> SimulationResult: ...


@overload
def simulate(
    circuit: CircuitIR,
    *,
    trace: _TraceCaptureRequest[_TraceArtifact],
) -> SimulationExecution[SimulationResult, _TraceArtifact]: ...


@overload
def simulate(
    circuit: CircuitIR,
    *,
    execution: SampledExecutionRequest,
) -> SampledSimulationResult: ...


@overload
def simulate(
    circuit: CircuitIR,
    *,
    execution: SampledExecutionRequest,
    trace: _TraceCaptureRequest[_TraceArtifact],
) -> SimulationExecution[SampledSimulationResult, _TraceArtifact]: ...


def simulate(
    circuit: CircuitIR,
    *,
    trace: _TraceCaptureRequest[object] | None = None,
    execution: SampledExecutionRequest | None = None,
) -> (
    SimulationResult
    | SampledSimulationResult
    | SimulationExecution[SimulationResult, object]
    | SimulationExecution[SampledSimulationResult, object]
):
    """Run exact or sampled state-vector execution with optional trace capture.

    The legacy no-keyword form returns ``SimulationResult``. Supplying a trace
    request returns ``SimulationExecution`` regardless of whether capture is
    enabled, avoiding a return-type change based on the option value itself. A
    sampled trace represents one trajectory, so enabled capture requires one shot.
    """

    if execution is not None:
        if trace is not None and trace.enabled and execution.shots != 1:
            raise SampledTraceShotCountError(execution.shots)
        captured_execution = _simulate_sampled_execution(
            circuit,
            execution,
            retain_trace=trace is not None and trace.enabled,
        )
        if trace is None:
            return captured_execution.result
        if captured_execution.trace is None:
            return SimulationExecution(captured_execution.result, None)
        shot = captured_execution.result.shots[0]
        return SimulationExecution(
            captured_execution.result,
            trace.build_execution_trace(
                shot.result,
                captured_execution.trace,
                sampled=True,
                seed=execution.seed,
            ),
        )

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
        trace.build_execution_trace(
            captured_execution.result,
            captured_execution.trace,
            sampled=False,
            seed=None,
        ),
    )


def _simulate_execution(
    circuit: CircuitIR,
    *,
    retain_trace: bool,
) -> SimulationExecution[SimulationResult, SimulationTrace]:
    size = 1 << circuit.qubit_count
    state = [0j] * size
    state[0] = 1 + 0j
    initial_amplitudes = tuple(state) if retain_trace else None
    steps: list[SimulationTraceStep] | None = [] if retain_trace else None
    terminal_observation: tuple[IrOperationId, int] | None = None

    for index, operation in enumerate(circuit.operations):
        if operation.opcode is OpCode.RESET:
            raise ExactResetUnsupportedError(operation_id=operation.id, step_index=index)
        if terminal_observation is not None and operation.opcode is not OpCode.MEASURE:
            observed_operation_id, observed_step_index = terminal_observation
            raise ExactTerminalObservationError(
                observed_operation_id=observed_operation_id,
                observed_step_index=observed_step_index,
                following_operation_id=operation.id,
                following_step_index=index,
            )
        if operation.opcode is OpCode.MEASURE and terminal_observation is None:
            terminal_observation = (operation.id, index)
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


def _simulate_sampled_execution(
    circuit: CircuitIR,
    request: SampledExecutionRequest,
    *,
    retain_trace: bool,
) -> SimulationExecution[SampledSimulationResult, SimulationTrace]:
    random = Random(request.seed)
    shots: list[SampledSimulationShot] = []
    captured_trace: SimulationTrace | None = None
    for shot_index in range(request.shots):
        shot, trace = _simulate_sampled_shot(
            circuit,
            shot_index=shot_index,
            random=random,
            retain_trace=retain_trace,
        )
        shots.append(shot)
        if trace is not None:
            captured_trace = trace
    return SimulationExecution(
        SampledSimulationResult(circuit, tuple(shots), request.seed),
        captured_trace,
    )


def _simulate_sampled_shot(
    circuit: CircuitIR,
    *,
    shot_index: int,
    random: Random,
    retain_trace: bool,
) -> tuple[SampledSimulationShot, SimulationTrace | None]:
    size = 1 << circuit.qubit_count
    state = [0j] * size
    state[0] = 1 + 0j
    initial_amplitudes = tuple(state) if retain_trace else None
    steps: list[SimulationTraceStep] | None = [] if retain_trace else None
    measurement_outcomes: list[SimulationMeasurementOutcome] = []
    reset_events: list[SimulationResetEvent] = []

    for index, operation in enumerate(circuit.operations):
        before_amplitudes = tuple(state) if retain_trace else None
        measurement_outcome = None
        reset_event = None
        if operation.opcode is OpCode.MEASURE:
            measurement_outcome = _sample_measurement(
                state,
                operation.targets,
                random,
            )
            measurement_outcomes.append(
                SimulationMeasurementOutcome(
                    operation_id=operation.id,
                    targets=operation.targets,
                    outcome=measurement_outcome,
                )
            )
        elif operation.opcode is OpCode.RESET:
            if len(operation.targets) != 1:
                raise ValueError("RESET operations require exactly one target")
            reset_event = _sample_reset(state, operation, random)
            reset_events.append(reset_event)
        else:
            state = apply_operation(state, operation)
        _validate_state_norm(state, operation=operation, step_index=index)

        if steps is not None:
            assert before_amplitudes is not None
            steps.append(
                SimulationTraceStep(
                    index=index,
                    operation=operation,
                    before_amplitudes=before_amplitudes,
                    after_amplitudes=tuple(state),
                    measurement_outcome=measurement_outcome,
                    reset_event=reset_event,
                )
            )

    result = SimulationResult(circuit, tuple(state))
    captured_trace = None
    if steps is not None:
        assert initial_amplitudes is not None
        captured_trace = SimulationTrace(initial_amplitudes, tuple(steps))
    return (
        SampledSimulationShot(
            index=shot_index,
            result=result,
            measurement_outcomes=tuple(measurement_outcomes),
            reset_events=tuple(reset_events),
        ),
        captured_trace,
    )


def _sample_measurement(
    state: list[complex],
    targets: tuple[int, ...],
    random: Random,
) -> tuple[int, ...]:
    probabilities = _measurement_probabilities(state, targets)
    outcome_index = _sample_outcome(probabilities, random)
    _collapse_measurement(state, targets, outcome_index, probabilities[outcome_index])
    return tuple((outcome_index >> index) & 1 for index in range(len(targets)))


def _sample_reset(
    state: list[complex],
    operation: Operation,
    random: Random,
) -> SimulationResetEvent:
    target = operation.targets[0]
    outcome = _sample_measurement(state, (target,), random)[0]
    if outcome == 1:
        _apply_single(state, target, 0j, 1 + 0j, 1 + 0j, 0j)
    return SimulationResetEvent(
        operation_id=operation.id,
        target=target,
        sampled_internal_outcome=outcome,
    )


def _sample_outcome(probabilities: tuple[float, ...], random: Random) -> int:
    draw = random.random()
    cumulative = 0.0
    for outcome, probability in enumerate(probabilities):
        cumulative += probability
        if draw < cumulative:
            return outcome
    return len(probabilities) - 1


def _require_nonempty_operation_id(operation_id: IrOperationId, *, label: str) -> None:
    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError(f"{label} must be a non-empty string")


def _collapse_measurement(
    state: list[complex],
    targets: tuple[int, ...],
    outcome: int,
    probability: float,
) -> None:
    if probability <= 0:
        raise ValueError("cannot collapse a sampled measurement onto a zero-probability outcome")
    scale = 1 / sqrt(probability)
    for basis_index, amplitude in enumerate(state):
        observed = 0
        for outcome_bit, target in enumerate(targets):
            if basis_index & (1 << target):
                observed |= 1 << outcome_bit
        state[basis_index] = amplitude * scale if observed == outcome else 0j


def apply_operation(state: list[complex], operation: Operation) -> list[complex]:
    """Deterministically mutate ``state`` for one IR operation without tracing."""

    if operation.opcode is OpCode.X:
        _apply_single(state, operation.targets[0], 0j, 1 + 0j, 1 + 0j, 0j)
    elif operation.opcode is OpCode.H:
        scale = 1 / sqrt(2)
        _apply_single(state, operation.targets[0], scale, scale, scale, -scale)
    elif operation.opcode is OpCode.Z:
        _apply_single(state, operation.targets[0], 1 + 0j, 0j, 0j, -1 + 0j)
    elif operation.opcode is OpCode.RX:
        _apply_rotation(state, operation.targets[0], operation.angle_radians, axis="x")
    elif operation.opcode is OpCode.RY:
        _apply_rotation(state, operation.targets[0], operation.angle_radians, axis="y")
    elif operation.opcode is OpCode.RZ:
        _apply_rotation(state, operation.targets[0], operation.angle_radians, axis="z")
    elif operation.opcode is OpCode.CX:
        _apply_cx(state, operation.controls[0], operation.targets[0])
    elif operation.opcode is OpCode.MEASURE:
        # Exact terminal projection retains the analytical pre-observation state.
        # Sampling and collapse require an explicit future runtime policy.
        return state
    elif operation.opcode is OpCode.RESET:
        raise ExactResetUnsupportedError(operation_id=operation.id)
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


def _apply_rotation(
    state: list[complex],
    target: int,
    angle_radians: float | None,
    *,
    axis: str,
) -> None:
    if angle_radians is None:  # pragma: no cover - protected by IR validation
        raise ValueError("rotation operations require angle_radians")
    half_angle = angle_radians / 2
    cosine = cos(half_angle)
    sine = sin(half_angle)
    if axis == "x":
        _apply_single(state, target, cosine, -1j * sine, -1j * sine, cosine)
    elif axis == "y":
        _apply_single(state, target, cosine, -sine, sine, cosine)
    elif axis == "z":
        _apply_single(
            state,
            target,
            cosine - 1j * sine,
            0j,
            0j,
            cosine + 1j * sine,
        )
    else:  # pragma: no cover - only fixed axes are passed above
        raise ValueError(f"unsupported rotation axis: {axis}")


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
