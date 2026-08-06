from __future__ import annotations

from dataclasses import dataclass

from ariadion_core import IrOperationId, ProgramId, SourceRef, canonical_json
from ariadion_ir import OpCode
from theonoe import (
    DEFAULT_EPSILON,
    SEPARABILITY_ABS_TOLERANCE,
    StateReport,
    StateTransition,
    inspect_amplitudes,
    inspect_state_transition,
)

from .trace import ExecutionTrace, MeasurementEvent


@dataclass(frozen=True, slots=True)
class TraceStepInspection:
    """Theonoe analysis and immutable operation identity for one trace step."""

    index: int
    ir_operation_id: IrOperationId
    opcode: OpCode
    targets: tuple[int, ...]
    controls: tuple[int, ...]
    key: str | None
    source: SourceRef | None
    measurement: MeasurementEvent | None
    transition: StateTransition

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "ir_operation_id": self.ir_operation_id,
            "operation": {
                "opcode": self.opcode.value,
                "targets": list(self.targets),
                "controls": list(self.controls),
                "key": self.key,
                "source": self.source.to_dict() if self.source is not None else None,
            },
            "measurement": self.measurement.to_dict() if self.measurement is not None else None,
            "transition": self.transition.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class TraceInspection:
    """Structured, step-by-step Theonoe analysis of an execution trace."""

    circuit_id: ProgramId
    trace_schema_version: int
    initial: StateReport
    steps: tuple[TraceStepInspection, ...]

    @property
    def final(self) -> StateReport:
        return self.steps[-1].transition.after if self.steps else self.initial

    def to_dict(self) -> dict[str, object]:
        return {
            "circuit_id": self.circuit_id,
            "trace_schema_version": self.trace_schema_version,
            "initial": self.initial.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "final": self.final.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def inspect_execution_trace(
    trace: ExecutionTrace,
    *,
    epsilon: float = DEFAULT_EPSILON,
    separability_tolerance: float = SEPARABILITY_ABS_TOLERANCE,
) -> TraceInspection:
    """Inspect every immutable trace snapshot without mutating the trace itself."""

    initial = inspect_amplitudes(
        trace.initial_state.amplitudes,
        trace.initial_state.qubit_count,
        epsilon=epsilon,
        separability_tolerance=separability_tolerance,
    )
    steps = tuple(
        TraceStepInspection(
            index=step.index,
            ir_operation_id=step.ir_operation_id,
            opcode=step.operation.opcode,
            targets=step.operation.targets,
            controls=step.operation.controls,
            key=step.operation.key,
            source=step.source,
            measurement=step.measurement,
            transition=inspect_state_transition(
                step.before.amplitudes,
                step.after.amplitudes,
                step.before.qubit_count,
                epsilon=epsilon,
                separability_tolerance=separability_tolerance,
            ),
        )
        for step in trace.steps
    )
    return TraceInspection(trace.circuit_id, trace.schema_version, initial, steps)
