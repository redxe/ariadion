from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from ariadion_core import (
    IrOperationId,
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SnapshotOperationId,
    SourceIdentity,
    SourceNodeId,
    SourceOperationId,
    SourceRange,
    SourceRef,
    canonical_json,
    require_nonempty_identifier,
)
from ariadion_ir import (
    AngleMetadata,
    CircuitIR,
    OpCode,
    Operation,
    OperationProvenance,
)
from ariadion_language import Angle, Program, SourceOperation
from ariadion_semantics import (
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalProgram,
    Observation,
)


class DiagnosticSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    operation_index: int | None = None
    source: SourceRef | None = None
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    logical_operation_id: LogicalOperationId | None = None

    @property
    def source_id(self) -> SourceIdentity | None:
        return self.source.source_id if self.source is not None else None

    @property
    def source_range(self) -> SourceRange | None:
        return self.source.source_range if self.source is not None else None

    @property
    def program_id(self) -> ProgramId | None:
        return self.source.program_id if self.source is not None else None

    @property
    def snapshot_operation_id(self) -> SnapshotOperationId | None:
        return self.source.snapshot_operation_id if self.source is not None else None

    @property
    def source_operation_id(self) -> SourceOperationId | None:
        return self.source.source_operation_id if self.source is not None else None

    @property
    def source_node_id(self) -> SourceNodeId | None:
        return self.source.source_node_id if self.source is not None else None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "operation_index": self.operation_index,
            "severity": self.severity.value,
            "logical_operation_id": self.logical_operation_id,
            "source": self.source.to_dict() if self.source is not None else None,
        }


class CompileError(ValueError):
    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


LOGICAL_ALLOCATION_POLICY_NAME: Final = "dense-no-reuse-v1"
_LOGICAL_LOWERING_TRANSFORMATION: Final = "logical-allocation-lowering"
_Z_BASIS_NAME: Final = "z"


@dataclass(frozen=True, slots=True)
class AllocationEntry:
    """The allocated slot selected for one logical quantum value."""

    logical_qubit_id: LogicalQubitId
    slot: int

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.logical_qubit_id,
            label="allocation logical qubit ID",
        )
        _require_nonnegative_int(self.slot, label="allocation slot")

    def to_dict(self) -> dict[str, object]:
        return {"logical_qubit_id": self.logical_qubit_id, "slot": self.slot}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    """A deterministic allocation artifact kept separate from allocated IR."""

    policy_name: str
    entries: tuple[AllocationEntry, ...]
    peak_live_qubits: int
    allocated_qubit_count: int

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.policy_name, label="allocation policy name")
        if not isinstance(self.entries, tuple):
            raise ValueError("allocation plan entries must be a tuple")
        if not all(isinstance(entry, AllocationEntry) for entry in self.entries):
            raise ValueError("allocation plan entries must contain AllocationEntry values")
        logical_ids = tuple(entry.logical_qubit_id for entry in self.entries)
        if len(logical_ids) != len(set(logical_ids)):
            raise ValueError("allocation plan logical qubit IDs must be unique")
        _require_nonnegative_int(
            self.peak_live_qubits,
            label="allocation peak_live_qubits",
        )
        _require_nonnegative_int(
            self.allocated_qubit_count,
            label="allocation allocated_qubit_count",
        )
        if self.peak_live_qubits > self.allocated_qubit_count:
            raise ValueError("allocation peak_live_qubits cannot exceed allocated_qubit_count")
        if any(entry.slot >= self.allocated_qubit_count for entry in self.entries):
            raise ValueError("allocation entry slot must fit allocated_qubit_count")
        if self.policy_name == LOGICAL_ALLOCATION_POLICY_NAME:
            expected_slots = tuple(range(len(self.entries)))
            if tuple(entry.slot for entry in self.entries) != expected_slots:
                raise ValueError(
                    "dense-no-reuse allocation entries must use declaration-order dense slots"
                )
            if self.peak_live_qubits != len(self.entries):
                raise ValueError(
                    "dense-no-reuse allocation peak_live_qubits must equal entry count"
                )
            if self.allocated_qubit_count != len(self.entries):
                raise ValueError(
                    "dense-no-reuse allocation allocated_qubit_count must equal entry count"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_name": self.policy_name,
            "entries": [entry.to_dict() for entry in self.entries],
            "peak_live_qubits": self.peak_live_qubits,
            "allocated_qubit_count": self.allocated_qubit_count,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalCompilationResult:
    """Allocated IR and the logical-value allocation that produced it."""

    ir: CircuitIR
    allocation: AllocationPlan

    def __post_init__(self) -> None:
        if not isinstance(self.ir, CircuitIR):
            raise ValueError("logical compilation result ir must be CircuitIR")
        if not isinstance(self.allocation, AllocationPlan):
            raise ValueError("logical compilation result allocation must be AllocationPlan")
        if self.ir.qubit_count != self.allocation.allocated_qubit_count:
            raise ValueError(
                "logical compilation result IR qubit_count must match allocated_qubit_count"
            )

    def to_dict(self) -> dict[str, object]:
        return {"ir": self.ir.to_dict(), "allocation": self.allocation.to_dict()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


_OPCODE_MAP = {
    "x": OpCode.X,
    "h": OpCode.H,
    "z": OpCode.Z,
    "rx": OpCode.RX,
    "ry": OpCode.RY,
    "rz": OpCode.RZ,
    "cx": OpCode.CX,
    "measure": OpCode.MEASURE,
}

_ROTATION_NAMES = frozenset({"rx", "ry", "rz"})
_LOGICAL_GATE_OPCODE_MAP = {
    LogicalGateOpCode.X: OpCode.X,
    LogicalGateOpCode.H: OpCode.H,
    LogicalGateOpCode.Z: OpCode.Z,
    LogicalGateOpCode.CX: OpCode.CX,
}


def compile_program(program: Program) -> CircuitIR:
    diagnostics = _validate(program)
    if diagnostics:
        raise CompileError(tuple(diagnostics))

    operations = tuple(_lower(program, operation) for operation in program.operations)
    return CircuitIR(program.id, program.name, program.qubit_count, operations)


def compile_logical_program(program: LogicalProgram) -> LogicalCompilationResult:
    """Allocate and lower a hand-built logical program without reusing slots."""

    if not isinstance(program, LogicalProgram):
        raise ValueError("logical program compiler input must be LogicalProgram")
    diagnostics = _validate_logical_lowering(program)
    if diagnostics:
        raise CompileError(tuple(diagnostics))

    allocation = _allocate_logical_program(program)
    slots = {entry.logical_qubit_id: entry.slot for entry in allocation.entries}
    operations = tuple(
        _lower_logical_instruction(instruction, slots)
        for instruction in program.instructions
    )
    return LogicalCompilationResult(
        ir=CircuitIR(
            program.id,
            program.name,
            allocation.allocated_qubit_count,
            operations,
        ),
        allocation=allocation,
    )


def _validate(program: Program) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if program.qubit_count <= 0:
        diagnostics.append(Diagnostic("A100", "program must declare at least one qubit"))

    for index, operation in enumerate(program.operations):
        all_qubits = operation.controls + operation.targets
        for qubit in all_qubits:
            if not isinstance(qubit, int):
                diagnostics.append(
                    _operation_diagnostic(
                        program,
                        index,
                        operation,
                        "A101",
                        f"qubit reference must be an integer: {qubit!r}",
                    )
                )
            elif qubit < 0 or qubit >= program.qubit_count:
                diagnostics.append(
                    _operation_diagnostic(
                        program,
                        index,
                        operation,
                        "A102",
                        f"qubit {qubit} is outside program width {program.qubit_count}",
                    )
                )
        if operation.name == "cx" and operation.controls == operation.targets:
            diagnostics.append(
                _operation_diagnostic(
                    program,
                    index,
                    operation,
                    "A103",
                    "controlled-X requires distinct control and target qubits",
                )
            )
        if operation.name not in _OPCODE_MAP:
            diagnostics.append(
                _operation_diagnostic(
                    program,
                    index,
                    operation,
                    "A104",
                    f"unsupported operation {operation.name!r}",
                )
            )
        elif operation.name in _ROTATION_NAMES and not isinstance(
            operation.angle,
            Angle,
        ):
            diagnostics.append(
                _operation_diagnostic(
                    program,
                    index,
                    operation,
                    "A105",
                    f"{operation.name.upper()} expects an angle. "
                    "Use rad(2) or deg(2).",
                )
            )
    return diagnostics


def _validate_logical_lowering(program: LogicalProgram) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for index, instruction in enumerate(program.instructions):
        if isinstance(instruction, LogicalGateOperation):
            if instruction.opcode not in _LOGICAL_GATE_OPCODE_MAP:
                diagnostics.append(
                    _logical_instruction_diagnostic(
                        index,
                        instruction,
                        "A200",
                        f"logical gate {instruction.opcode.value!r} has no supported lowering",
                    )
                )
        elif instruction.basis.name != _Z_BASIS_NAME:
            diagnostics.append(
                _logical_instruction_diagnostic(
                    index,
                    instruction,
                    "A201",
                    "only z-basis observations are supported by logical allocation lowering; "
                    f"received {instruction.basis.name!r}",
                )
            )
    return diagnostics


def _lower(program: Program, operation: SourceOperation) -> Operation:
    source = _source_ref(program, operation)
    angle_radians = None
    angle_metadata = None
    if operation.name in _ROTATION_NAMES:
        angle = operation.angle
        if not isinstance(angle, Angle):  # pragma: no cover - validated before lowering
            raise RuntimeError("rotation lowering requires an explicit Angle")
        angle_radians = angle.radians
        angle_metadata = AngleMetadata(angle.source_value, angle.source_unit.value)
    return Operation(
        opcode=_OPCODE_MAP[operation.name],
        targets=operation.targets,
        id=make_ir_operation_id(source, "source-lowering", 0),
        controls=operation.controls,
        key=operation.key,
        source=source,
        angle_radians=angle_radians,
        angle_metadata=angle_metadata,
    )


def _allocate_logical_program(program: LogicalProgram) -> AllocationPlan:
    entries = tuple(AllocationEntry(qubit.id, slot) for slot, qubit in enumerate(program.qubits))
    return AllocationPlan(
        policy_name=LOGICAL_ALLOCATION_POLICY_NAME,
        entries=entries,
        peak_live_qubits=len(entries),
        allocated_qubit_count=len(entries),
    )


def _lower_logical_instruction(
    instruction: LogicalGateOperation | Observation,
    slots: dict[LogicalQubitId, int],
) -> Operation:
    if isinstance(instruction, LogicalGateOperation):
        opcode = _LOGICAL_GATE_OPCODE_MAP[instruction.opcode]
        targets = tuple(slots[qubit_id] for qubit_id in instruction.targets)
        controls = tuple(slots[qubit_id] for qubit_id in instruction.controls)
    else:
        opcode = OpCode.MEASURE
        targets = (slots[instruction.qubit_id],)
        controls = ()
    source = instruction.source
    parent_source_ids = (source.source_operation_id,) if source is not None else ()
    return Operation(
        opcode=opcode,
        targets=targets,
        id=make_logical_ir_operation_id(
            instruction.id,
            _LOGICAL_LOWERING_TRANSFORMATION,
            0,
        ),
        controls=controls,
        source=source,
        provenance=OperationProvenance(
            parent_source_ids=parent_source_ids,
            transformation=_LOGICAL_LOWERING_TRANSFORMATION,
            parent_logical_operation_ids=(instruction.id,),
        ),
    )


def _operation_diagnostic(
    program: Program,
    index: int,
    operation: SourceOperation,
    code: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(code, message, index, _source_ref(program, operation))


def _logical_instruction_diagnostic(
    index: int,
    instruction: LogicalGateOperation | Observation,
    code: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(
        code,
        message,
        index,
        instruction.source,
        logical_operation_id=instruction.id,
    )


def make_ir_operation_id(
    source: SourceRef,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    return _make_ir_operation_id(
        source.source_operation_id,
        transformation,
        output_index,
    )


def make_logical_ir_operation_id(
    logical_operation_id: LogicalOperationId,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    """Create an IR ID from semantic instruction identity rather than source IDs."""

    return _make_ir_operation_id(logical_operation_id, transformation, output_index)


def _make_ir_operation_id(
    parent_operation_id: str,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    require_nonempty_identifier(parent_operation_id, label="IR parent operation ID")
    require_nonempty_identifier(transformation, label="IR transformation")
    if not isinstance(output_index, int) or output_index < 0:
        raise ValueError("IR transformation output index must be a non-negative integer")
    return IrOperationId(
        f"{parent_operation_id}:daidalon:{transformation}:{output_index}"
    )


def _source_ref(program: Program, operation: SourceOperation) -> SourceRef:
    return SourceRef.from_range(
        program_id=program.id,
        source_range=operation.source_range,
        source_operation_id=SourceOperationId(operation.id),
        snapshot_operation_id=operation.id,
        source_node_id=operation.source_node_id,
    )


def _require_nonnegative_int(value: object, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
