from __future__ import annotations

from dataclasses import dataclass

from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_language import Program, SourceOperation


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    operation_index: int | None = None


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

    operations = tuple(_lower(operation) for operation in program.operations)
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
                    Diagnostic("A101", f"qubit reference must be an integer: {qubit!r}", index)
                )
            elif qubit < 0 or qubit >= program.qubit_count:
                diagnostics.append(
                    Diagnostic(
                        "A102",
                        f"qubit {qubit} is outside program width {program.qubit_count}",
                        index,
                    )
                )
        if operation.name == "cx" and operation.controls == operation.targets:
            diagnostics.append(
                Diagnostic("A103", "controlled-X requires distinct control and target qubits", index)
            )
        if operation.name not in _OPCODE_MAP:
            diagnostics.append(Diagnostic("A104", f"unsupported operation {operation.name!r}", index))
    return diagnostics


def _lower(operation: SourceOperation) -> Operation:
    return Operation(
        opcode=_OPCODE_MAP[operation.name],
        targets=operation.targets,
        controls=operation.controls,
        key=operation.key,
    )
