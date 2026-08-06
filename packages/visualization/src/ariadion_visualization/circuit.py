from __future__ import annotations

from ariadion_ir import CircuitIR, OpCode


def render_circuit(
    circuit: CircuitIR,
    *,
    active_operation_index: int | None = None,
) -> str:
    if active_operation_index is not None:
        if isinstance(active_operation_index, bool) or not isinstance(
            active_operation_index,
            int,
        ):
            raise ValueError("active operation index must be an integer")
        if not 0 <= active_operation_index < len(circuit.operations):
            raise ValueError("active operation index must select a circuit operation")

    lanes = [[f"q{qubit}: "] for qubit in range(circuit.qubit_count)]

    for index, operation in enumerate(circuit.operations):
        cells = ["─────" for _ in range(circuit.qubit_count)]
        is_active = index == active_operation_index
        horizontal = "═" if is_active else "─"
        if operation.opcode in {OpCode.X, OpCode.H, OpCode.Z}:
            cells[operation.targets[0]] = f"{horizontal}[{operation.opcode.value}]{horizontal}"
        elif operation.opcode is OpCode.MEASURE:
            cells[operation.targets[0]] = f"{horizontal}[M]{horizontal}"
        elif operation.opcode is OpCode.CX:
            control = operation.controls[0]
            target = operation.targets[0]
            cells[control] = f"{horizontal}{horizontal}●{horizontal}{horizontal}"
            cells[target] = f"{horizontal}[X]{horizontal}"
            low, high = sorted((control, target))
            for qubit in range(low + 1, high):
                cells[qubit] = f"{horizontal}{horizontal}│{horizontal}{horizontal}"
        for qubit, cell in enumerate(cells):
            lanes[qubit].append(cell)

    return "\n".join("".join(parts) for parts in lanes)
