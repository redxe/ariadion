from __future__ import annotations

from ariadion_ir import CircuitIR, OpCode


def render_circuit(circuit: CircuitIR) -> str:
    lanes = [[f"q{qubit}: "] for qubit in range(circuit.qubit_count)]

    for operation in circuit.operations:
        cells = ["─────" for _ in range(circuit.qubit_count)]
        if operation.opcode in {OpCode.X, OpCode.H, OpCode.Z}:
            cells[operation.targets[0]] = f"─[{operation.opcode.value}]─"
        elif operation.opcode is OpCode.MEASURE:
            cells[operation.targets[0]] = "─[M]─"
        elif operation.opcode is OpCode.CX:
            control = operation.controls[0]
            target = operation.targets[0]
            cells[control] = "──●──"
            cells[target] = "─[X]─"
            low, high = sorted((control, target))
            for qubit in range(low + 1, high):
                cells[qubit] = "──│──"
        for qubit, cell in enumerate(cells):
            lanes[qubit].append(cell)

    return "\n".join("".join(parts) for parts in lanes)
