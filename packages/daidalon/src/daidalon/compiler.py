from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ariadion_core import (
    IrOperationId,
    ProgramId,
    SnapshotOperationId,
    SourceIdentity,
    SourceNodeId,
    SourceRange,
    SourceRef,
    require_nonempty_identifier,
)
from ariadion_ir import AngleMetadata, CircuitIR, OpCode, Operation
from ariadion_language import Angle, Program, SourceOperation


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
    def source_node_id(self) -> SourceNodeId | None:
        return self.source.source_node_id if self.source is not None else None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "operation_index": self.operation_index,
            "severity": self.severity.value,
            "source": self.source.to_dict() if self.source is not None else None,
        }


class CompileError(ValueError):
    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


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


def compile_program(program: Program) -> CircuitIR:
    diagnostics = _validate(program)
    if diagnostics:
        raise CompileError(tuple(diagnostics))

    operations = tuple(_lower(program, operation) for operation in program.operations)
    return CircuitIR(program.id, program.name, program.qubit_count, operations)


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


def _operation_diagnostic(
    program: Program,
    index: int,
    operation: SourceOperation,
    code: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(code, message, index, _source_ref(program, operation))


def make_ir_operation_id(
    source: SourceRef,
    transformation: str,
    output_index: int,
) -> IrOperationId:
    require_nonempty_identifier(transformation, label="IR transformation")
    if not isinstance(output_index, int) or output_index < 0:
        raise ValueError("IR transformation output index must be a non-negative integer")
    return IrOperationId(
        f"{source.snapshot_operation_id}:daidalon:{transformation}:{output_index}"
    )


def _source_ref(program: Program, operation: SourceOperation) -> SourceRef:
    return SourceRef.from_range(
        program_id=program.id,
        snapshot_operation_id=operation.id,
        source_range=operation.source_range,
        source_node_id=operation.source_node_id,
    )
