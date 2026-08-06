from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from ariadion_core import IrOperationId, SourceRef, canonical_json
from ariadion_ir import CircuitIR, Operation, OperationProvenance
from theonoe import (
    BasisStateChange,
    EntanglementTransition,
    RotationExplanation,
    StateReport,
)

from .inspection import TraceInspection, TraceStepInspection
from .trace import ExecutionTrace, MeasurementEvent, TraceStep


TRACE_DEBUGGER_SCHEMA_VERSION: Final = 1


class TraceDebuggerError(ValueError):
    """Raised when a trace cannot produce a consistent debugger view."""


@dataclass(frozen=True, slots=True)
class TraceStepViewModel:
    """Frontend-neutral data for rendering one inspected trace operation."""

    circuit: CircuitIR
    step_index: int
    step_count: int
    operation: Operation
    ir_operation_id: IrOperationId
    source: SourceRef | None
    provenance: OperationProvenance | None
    before: StateReport
    after: StateReport
    basis_state_changes: tuple[BasisStateChange, ...]
    entanglement: EntanglementTransition
    global_phase_delta_radians: float | None
    measurement: MeasurementEvent | None
    rotation_explanation: RotationExplanation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.circuit, CircuitIR):
            raise TraceDebuggerError("trace view circuit must be CircuitIR")
        if isinstance(self.step_index, bool) or not isinstance(self.step_index, int):
            raise TraceDebuggerError("trace view step_index must be an integer")
        if isinstance(self.step_count, bool) or not isinstance(self.step_count, int):
            raise TraceDebuggerError("trace view step_count must be an integer")
        if not 0 <= self.step_index < self.step_count:
            raise TraceDebuggerError("trace view step_index must select an operation step")
        if not isinstance(self.operation, Operation):
            raise TraceDebuggerError("trace view operation must be an IR Operation")
        if self.ir_operation_id != self.operation.id:
            raise TraceDebuggerError("trace view operation ID must match the operation")
        if self.source != self.operation.source:
            raise TraceDebuggerError("trace view source must match the operation")
        if self.provenance != self.operation.provenance:
            raise TraceDebuggerError("trace view provenance must match the operation")
        if self.rotation_explanation is not None and not isinstance(
            self.rotation_explanation,
            RotationExplanation,
        ):
            raise TraceDebuggerError(
                "trace view rotation_explanation must be RotationExplanation"
            )

    @property
    def step_number(self) -> int:
        """Return the one-based step number used by interactive frontends."""

        return self.step_index + 1

    def to_dict(self) -> dict[str, object]:
        return {
            "circuit_id": self.circuit.id,
            "step_index": self.step_index,
            "step_number": self.step_number,
            "step_count": self.step_count,
            "ir_operation_id": self.ir_operation_id,
            "operation": self.operation.to_dict(),
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "basis_state_changes": [
                change.to_dict() for change in self.basis_state_changes
            ],
            "entanglement": self.entanglement.to_dict(),
            "global_phase_delta_radians": self.global_phase_delta_radians,
            "measurement": self.measurement.to_dict() if self.measurement is not None else None,
            "rotation_explanation": (
                self.rotation_explanation.to_dict()
                if self.rotation_explanation is not None
                else None
            ),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class TraceDebuggerSession:
    """Immutable navigation state over one inspected execution trace."""

    circuit: CircuitIR
    trace: ExecutionTrace
    inspection: TraceInspection
    current_step_index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.circuit, CircuitIR):
            raise TraceDebuggerError("debugger circuit must be CircuitIR")
        if not isinstance(self.trace, ExecutionTrace):
            raise TraceDebuggerError("debugger trace must be an ExecutionTrace")
        if not isinstance(self.inspection, TraceInspection):
            raise TraceDebuggerError("debugger inspection must be a TraceInspection")
        if self.circuit.id != self.trace.circuit_id:
            raise TraceDebuggerError("debugger circuit ID must match the execution trace")
        if self.inspection.circuit_id != self.trace.circuit_id:
            raise TraceDebuggerError("debugger inspection must match the execution trace")
        if self.inspection.trace_schema_version != self.trace.schema_version:
            raise TraceDebuggerError("debugger inspection schema must match the trace")
        if len(self.circuit.operations) != len(self.trace.steps):
            raise TraceDebuggerError("debugger circuit must contain every trace operation")
        if len(self.trace.steps) != len(self.inspection.steps):
            raise TraceDebuggerError("debugger inspection must contain every trace step")
        if isinstance(self.current_step_index, bool) or not isinstance(
            self.current_step_index,
            int,
        ):
            raise TraceDebuggerError("debugger current_step_index must be an integer")
        if self.trace.steps:
            self._validate_step_index(self.current_step_index)
        elif self.current_step_index != 0:
            raise TraceDebuggerError("an empty trace has no selectable operation step")

        for index, (circuit_operation, trace_step, inspection_step) in enumerate(
            zip(self.circuit.operations, self.trace.steps, self.inspection.steps)
        ):
            if circuit_operation != trace_step.operation:
                raise TraceDebuggerError("debugger circuit operations must match the trace")
            if trace_step.index != index or inspection_step.index != index:
                raise TraceDebuggerError("debugger steps must be contiguous from zero")
            if trace_step.ir_operation_id != inspection_step.ir_operation_id:
                raise TraceDebuggerError("debugger step operation IDs must match")
            if not _inspection_metadata_matches_trace(inspection_step, trace_step):
                raise TraceDebuggerError(
                    "debugger inspection metadata must match the trace operation"
                )

    @property
    def step_count(self) -> int:
        return len(self.trace.steps)

    @property
    def has_steps(self) -> bool:
        return bool(self.trace.steps)

    @property
    def current_view(self) -> TraceStepViewModel:
        if not self.has_steps:
            raise TraceDebuggerError("the execution trace has no operation steps")
        return self.view_at(self.current_step_index)

    def view_at(self, step_index: int) -> TraceStepViewModel:
        self._validate_step_index(step_index)
        trace_step = self.trace.steps[step_index]
        inspection_step = self.inspection.steps[step_index]
        transition = inspection_step.transition
        return TraceStepViewModel(
            circuit=self.circuit,
            step_index=step_index,
            step_count=self.step_count,
            operation=trace_step.operation,
            ir_operation_id=trace_step.ir_operation_id,
            source=trace_step.source,
            provenance=trace_step.provenance,
            before=transition.before,
            after=transition.after,
            basis_state_changes=transition.basis_state_changes,
            entanglement=transition.entanglement,
            global_phase_delta_radians=transition.global_phase_delta_radians,
            measurement=trace_step.measurement,
            rotation_explanation=inspection_step.rotation_explanation,
        )

    def next(self) -> TraceDebuggerSession:
        if not self.has_steps:
            return self
        return self.go_to(min(self.current_step_index + 1, self.step_count - 1))

    def previous(self) -> TraceDebuggerSession:
        if not self.has_steps:
            return self
        return self.go_to(max(self.current_step_index - 1, 0))

    def go_to(self, step_index: int) -> TraceDebuggerSession:
        self._validate_step_index(step_index)
        return replace(self, current_step_index=step_index)

    def to_dict(self) -> dict[str, object]:
        """Serialize the complete debugger document for structured frontends."""

        return {
            "schema_version": TRACE_DEBUGGER_SCHEMA_VERSION,
            "current_step_index": self.current_step_index,
            "circuit": self.circuit.to_dict(),
            "trace": self.trace.to_dict(),
            "inspection": self.inspection.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def _validate_step_index(self, step_index: int) -> None:
        if isinstance(step_index, bool) or not isinstance(step_index, int):
            raise TraceDebuggerError("debugger step index must be an integer")
        if not self.has_steps:
            raise TraceDebuggerError("the execution trace has no operation steps")
        if not 0 <= step_index < self.step_count:
            raise TraceDebuggerError(
                f"debugger step index must be between 0 and {self.step_count - 1}"
            )


def _inspection_metadata_matches_trace(
    inspection_step: TraceStepInspection,
    trace_step: TraceStep,
) -> bool:
    """Return whether an inspection step retains its corresponding trace metadata."""

    operation = trace_step.operation
    return (
        inspection_step.opcode is operation.opcode
        and inspection_step.targets == operation.targets
        and inspection_step.controls == operation.controls
        and inspection_step.key == operation.key
        and inspection_step.source == operation.source
        and inspection_step.provenance == operation.provenance
        and inspection_step.angle_radians == operation.angle_radians
        and inspection_step.angle_metadata == operation.angle_metadata
        and inspection_step.measurement == trace_step.measurement
    )
