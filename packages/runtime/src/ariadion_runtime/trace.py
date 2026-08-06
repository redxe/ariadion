from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isclose, isfinite
from typing import Final

from ariadion_core import (
    IrOperationId,
    ProgramId,
    SourceIdentity,
    SourceNodeId,
    SourceRange,
    SourceRef,
    canonical_json,
    require_nonempty_identifier,
)
from ariadion_ir import CircuitIR, OpCode, Operation, OperationProvenance
from ariadion_simulator import SimulationResult, SimulationTrace, SimulationTraceStep


EXECUTION_TRACE_SCHEMA_VERSION: Final = 1
_EXACT_MEASUREMENT_PROBABILITY_ABS_TOLERANCE: Final = 1e-12


class StateRepresentation(str, Enum):
    STATE_VECTOR = "state_vector"


class ExecutionMode(str, Enum):
    EXACT = "exact"
    SAMPLED = "sampled"


class MeasurementRecordKind(str, Enum):
    EXACT_PROBABILITIES = "exact_probabilities"
    SAMPLED_OUTCOME = "sampled_outcome"


class MeasurementBitOrder(str, Enum):
    """Maps target positions to outcome bit positions for every measurement."""

    TARGETS_LSB_FIRST = "targets_lsb_first"


@dataclass(frozen=True, slots=True)
class TraceCaptureOptions:
    """Controls whether a runtime producer retains intermediate snapshots."""

    enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("trace capture enabled must be a boolean")

    def to_dict(self) -> dict[str, bool]:
        return {"enabled": self.enabled}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def build_execution_trace(
        self,
        result: SimulationResult,
        captured_trace: SimulationTrace,
    ) -> ExecutionTrace:
        """Project raw backend capture to the public runtime trace contract."""

        if not self.enabled:
            raise ValueError("trace capture must be enabled to build an execution trace")
        return _execution_trace_from_capture(result, captured_trace)


@dataclass(frozen=True, slots=True)
class ResourceMetric:
    name: str
    value: float | int
    unit: str | None = None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.name, label="resource metric name")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("resource metric value must be numeric")
        if not isfinite(float(self.value)):
            raise ValueError("resource metric value must be finite")

    def to_dict(self) -> dict[str, str | float | int | None]:
        return {"name": self.name, "value": self.value, "unit": self.unit}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExecutionMetadata:
    mode: ExecutionMode = ExecutionMode.EXACT
    duration_ns: int | None = None
    seed: int | None = None
    resource_metrics: tuple[ResourceMetric, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ExecutionMode):
            raise ValueError("execution mode must be an ExecutionMode")
        if self.duration_ns is not None and (
            isinstance(self.duration_ns, bool)
            or not isinstance(self.duration_ns, int)
            or self.duration_ns < 0
        ):
            raise ValueError("execution duration_ns must be a non-negative integer")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("execution seed must be an integer when provided")
        _require_tuple(self.resource_metrics, label="execution resource_metrics")
        if not all(isinstance(metric, ResourceMetric) for metric in self.resource_metrics):
            raise ValueError("execution resource_metrics must contain ResourceMetric values")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "duration_ns": self.duration_ns,
            "seed": self.seed,
            "resource_metrics": [metric.to_dict() for metric in self.resource_metrics],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """An immutable exact state-vector snapshot for one circuit instant."""

    circuit_id: ProgramId
    qubit_count: int
    amplitudes: tuple[complex, ...]
    representation: StateRepresentation = StateRepresentation.STATE_VECTOR

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.circuit_id, label="circuit ID")
        if not isinstance(self.representation, StateRepresentation):
            raise ValueError("snapshot representation must be a StateRepresentation")
        if isinstance(self.qubit_count, bool) or not isinstance(self.qubit_count, int):
            raise ValueError("snapshot qubit_count must be an integer")
        if self.qubit_count < 0:
            raise ValueError("snapshot qubit_count must be non-negative")
        _require_tuple(self.amplitudes, label="snapshot amplitudes")
        if len(self.amplitudes) != 1 << self.qubit_count:
            raise ValueError("snapshot amplitude count must equal 2**qubit_count")
        if not all(isinstance(amplitude, complex) for amplitude in self.amplitudes):
            raise ValueError("snapshot amplitudes must be complex values")
        if any(
            not isfinite(amplitude.real) or not isfinite(amplitude.imag)
            for amplitude in self.amplitudes
        ):
            raise ValueError("snapshot amplitudes must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "circuit_id": self.circuit_id,
            "qubit_count": self.qubit_count,
            "representation": self.representation.value,
            "amplitudes": [_complex_to_dict(amplitude) for amplitude in self.amplitudes],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MeasurementEvent:
    """A measurement record that explicitly separates exact and sampled data.

    ``targets[i]`` maps to outcome bit ``i``. Therefore exact probability index
    ``outcome`` uses the least-significant bit for ``targets[0]``. Sampled
    ``outcome`` tuples are in target order, so ``outcome[i]`` belongs to
    ``targets[i]``. Serialized consumers must use ``bit_order`` rather than
    inferring this mapping from a displayed binary string.
    """

    operation_id: IrOperationId
    targets: tuple[int, ...]
    kind: MeasurementRecordKind
    key: str | None = None
    probabilities: tuple[float, ...] = ()
    outcome: tuple[int, ...] | None = None
    bit_order: MeasurementBitOrder = MeasurementBitOrder.TARGETS_LSB_FIRST

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.operation_id, label="measurement operation ID")
        if not isinstance(self.kind, MeasurementRecordKind):
            raise ValueError("measurement record kind must be a MeasurementRecordKind")
        if not isinstance(self.bit_order, MeasurementBitOrder):
            raise ValueError("measurement bit_order must be a MeasurementBitOrder")
        _require_tuple(self.targets, label="measurement targets")
        if not self.targets:
            raise ValueError("measurement targets must not be empty")
        if any(
            isinstance(target, bool) or not isinstance(target, int) or target < 0
            for target in self.targets
        ):
            raise ValueError("measurement targets must be non-negative integers")
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("measurement targets must be unique")
        _require_tuple(self.probabilities, label="measurement probabilities")

        if self.kind is MeasurementRecordKind.EXACT_PROBABILITIES:
            expected_probability_count = 1 << len(self.targets)
            if len(self.probabilities) != expected_probability_count:
                raise ValueError(
                    "measurement probability count must equal 2**target_count"
                )
            if self.outcome is not None:
                raise ValueError("exact measurement records cannot contain a sampled outcome")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or value < 0
                for value in self.probabilities
            ):
                raise ValueError("measurement probabilities must be finite non-negative values")
            if not isclose(
                sum(self.probabilities),
                1.0,
                rel_tol=0.0,
                abs_tol=_EXACT_MEASUREMENT_PROBABILITY_ABS_TOLERANCE,
            ):
                raise ValueError("measurement probabilities must sum to one")
        elif self.kind is MeasurementRecordKind.SAMPLED_OUTCOME:
            if self.probabilities:
                raise ValueError("sampled measurement records cannot contain exact probabilities")
            if self.outcome is None:
                raise ValueError("sampled measurement records require an outcome")
            _require_tuple(self.outcome, label="sampled measurement outcome")
            if len(self.outcome) != len(self.targets) or any(
                isinstance(bit, bool) or not isinstance(bit, int) or bit not in {0, 1}
                for bit in self.outcome
            ):
                raise ValueError("sampled measurement outcome must contain one bit per target")
        else:  # pragma: no cover - protects future enum expansion
            raise ValueError(f"unsupported measurement record kind: {self.kind}")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "targets": list(self.targets),
            "kind": self.kind.value,
            "key": self.key,
            "probabilities": list(self.probabilities),
            "outcome": list(self.outcome) if self.outcome is not None else None,
            "bit_order": self.bit_order.value,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class TraceStep:
    """The immutable state transition caused by one semantic IR operation."""

    index: int
    operation: Operation
    before: StateSnapshot
    after: StateSnapshot
    measurement: MeasurementEvent | None = None
    metadata: ExecutionMetadata | None = None

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError("trace step index must be a non-negative integer")
        if not isinstance(self.operation, Operation):
            raise ValueError("trace step operation must be an IR Operation")
        if not isinstance(self.before, StateSnapshot) or not isinstance(self.after, StateSnapshot):
            raise ValueError("trace step snapshots must be StateSnapshot values")
        if self.before.circuit_id != self.after.circuit_id:
            raise ValueError("trace step snapshots must belong to the same circuit")
        if self.before.qubit_count != self.after.qubit_count:
            raise ValueError("trace step snapshots must have matching qubit counts")
        if self.measurement is not None and not isinstance(self.measurement, MeasurementEvent):
            raise ValueError("trace step measurement must be a MeasurementEvent")
        if self.measurement is not None:
            if self.measurement.operation_id != self.operation.id:
                raise ValueError("measurement event operation ID must match its trace operation")
            if self.operation.opcode is not OpCode.MEASURE:
                raise ValueError("measurement events require a MEASURE operation")
            if self.measurement.targets != self.operation.targets:
                raise ValueError("measurement targets must match the trace operation")
            if self.measurement.key != self.operation.key:
                raise ValueError("measurement key must match the trace operation")
            if any(target >= self.before.qubit_count for target in self.measurement.targets):
                raise ValueError("measurement targets must be within the snapshot width")
        if self.metadata is not None and not isinstance(self.metadata, ExecutionMetadata):
            raise ValueError("trace step metadata must be ExecutionMetadata")

    @property
    def ir_operation_id(self) -> IrOperationId:
        return self.operation.id

    @property
    def source(self) -> SourceRef | None:
        return self.operation.source

    @property
    def source_id(self) -> SourceIdentity | None:
        return self.operation.source_id

    @property
    def source_node_id(self) -> SourceNodeId | None:
        return self.operation.source_node_id

    @property
    def source_range(self) -> SourceRange | None:
        return self.operation.source_range

    @property
    def provenance(self) -> OperationProvenance | None:
        return self.operation.provenance

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "operation": _operation_to_dict(self.operation),
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "measurement": self.measurement.to_dict() if self.measurement is not None else None,
            "metadata": self.metadata.to_dict() if self.metadata is not None else None,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    """A versioned, immutable sequence of exact state transitions for one circuit."""

    circuit_id: ProgramId
    initial_state: StateSnapshot
    steps: tuple[TraceStep, ...] = ()
    metadata: ExecutionMetadata = field(default_factory=ExecutionMetadata)
    schema_version: int = EXECUTION_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.circuit_id, label="circuit ID")
        if not isinstance(self.initial_state, StateSnapshot):
            raise ValueError("execution trace initial_state must be a StateSnapshot")
        if not isinstance(self.metadata, ExecutionMetadata):
            raise ValueError("execution trace metadata must be ExecutionMetadata")
        if self.initial_state.circuit_id != self.circuit_id:
            raise ValueError("initial state circuit ID must match the execution trace")
        _require_tuple(self.steps, label="execution trace steps")
        if not all(isinstance(step, TraceStep) for step in self.steps):
            raise ValueError("execution trace steps must contain TraceStep values")
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise ValueError("execution trace schema_version must be an integer")
        if self.schema_version < 1:
            raise ValueError("execution trace schema_version must be positive")
        operation_ids = tuple(step.ir_operation_id for step in self.steps)
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("trace IR operation IDs must be unique")

        previous = self.initial_state
        for expected_index, step in enumerate(self.steps):
            if step.index != expected_index:
                raise ValueError("execution trace step indexes must be contiguous from zero")
            if (
                step.before.circuit_id != self.circuit_id
                or step.after.circuit_id != self.circuit_id
            ):
                raise ValueError("execution trace steps must belong to the trace circuit")
            if step.before != previous:
                raise ValueError("each trace step must begin at the previous trace state")
            if step.source is not None and step.source.program_id != self.circuit_id:
                raise ValueError("trace operation source must belong to the trace circuit")
            if (
                self.metadata.mode is ExecutionMode.EXACT
                and step.measurement is not None
                and step.measurement.kind is MeasurementRecordKind.SAMPLED_OUTCOME
            ):
                raise ValueError(
                    "exact execution traces cannot contain sampled measurement outcomes"
                )
            previous = step.after

    @property
    def final_state(self) -> StateSnapshot:
        return self.steps[-1].after if self.steps else self.initial_state

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "circuit_id": self.circuit_id,
            "initial_state": self.initial_state.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "metadata": self.metadata.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def _complex_to_dict(value: complex) -> dict[str, float]:
    return {"real": value.real, "imaginary": value.imag}


def _operation_to_dict(operation: Operation) -> dict[str, object]:
    return operation.to_dict()


def _require_tuple(value: object, *, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple")


def _execution_trace_from_capture(
    result: SimulationResult,
    captured_trace: SimulationTrace,
) -> ExecutionTrace:
    circuit = result.circuit
    initial_state = StateSnapshot(
        circuit.id,
        circuit.qubit_count,
        captured_trace.initial_amplitudes,
    )
    steps = tuple(
        _trace_step_from_capture(circuit, captured_step)
        for captured_step in captured_trace.steps
    )
    return ExecutionTrace(
        circuit.id,
        initial_state,
        steps,
        metadata=ExecutionMetadata(mode=ExecutionMode.EXACT),
    )


def _trace_step_from_capture(
    circuit: CircuitIR,
    captured_step: SimulationTraceStep,
) -> TraceStep:
    operation = captured_step.operation
    measurement = None
    if captured_step.measurement_probabilities is not None:
        measurement = MeasurementEvent(
            operation.id,
            operation.targets,
            MeasurementRecordKind.EXACT_PROBABILITIES,
            key=operation.key,
            probabilities=captured_step.measurement_probabilities,
        )
    return TraceStep(
        captured_step.index,
        operation,
        StateSnapshot(circuit.id, circuit.qubit_count, captured_step.before_amplitudes),
        StateSnapshot(circuit.id, circuit.qubit_count, captured_step.after_amplitudes),
        measurement=measurement,
    )
