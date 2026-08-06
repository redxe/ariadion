from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ariadion_ir import CircuitIR, OpCode, Operation, OperationId, SourceRange, SourceRef
from ariadion_language import Program, SourceOperation


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
    def source_id(self) -> OperationId | None:
        return self.source.source_id if self.source is not None else None

    @property
    def source_range(self) -> SourceRange | None:
        return self.source.source_range if self.source is not None else None

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
    "cx": OpCode.CX,
    "measure": OpCode.MEASURE,
}


def compile_program(program: Program) -> CircuitIR:
    diagnostics = _validate(program)
    if diagnostics:
        raise CompileError(tuple(diagnostics))

    operations = tuple(
        _lower(program, index, operation) for index, operation in enumerate(program.operations)
    )
    return CircuitIR(program.name, program.qubit_count, operations)


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
    return diagnostics


def _lower(program: Program, index: int, operation: SourceOperation) -> Operation:
    return Operation(
        opcode=_OPCODE_MAP[operation.name],
        targets=operation.targets,
        controls=operation.controls,
        key=operation.key,
        source=_source_ref(program, index, operation),
    )


def _operation_diagnostic(
    program: Program,
    index: int,
    operation: SourceOperation,
    code: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(code, message, index, _source_ref(program, index, operation))


def _source_ref(program: Program, index: int, operation: SourceOperation) -> SourceRef:
    source_id = (
        operation.id
        if operation.id is not None
        else OperationId(f"{program.source_id}:operation:{index}")
    )
    return SourceRef.from_range(source_id, operation.source_range)
