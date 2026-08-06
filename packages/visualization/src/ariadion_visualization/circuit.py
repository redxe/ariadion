from __future__ import annotations

from ariadion_ir import CircuitIR, OpCode


_SINGLE_QUBIT_OPCODES = frozenset(
    {OpCode.X, OpCode.H, OpCode.Z, OpCode.RX, OpCode.RY, OpCode.RZ}
)


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
        is_active = index == active_operation_index
        horizontal = "═" if is_active else "─"
        cell_width = _operation_cell_width(operation.opcode)
        cells = [horizontal * cell_width for _ in range(circuit.qubit_count)]
        if operation.opcode in _SINGLE_QUBIT_OPCODES:
            cells[operation.targets[0]] = _symbol_cell(
                f"[{operation.opcode.value}]",
                cell_width,
                horizontal,
            )
        elif operation.opcode is OpCode.MEASURE:
            cells[operation.targets[0]] = _symbol_cell("[M]", cell_width, horizontal)
        elif operation.opcode is OpCode.CX:
            control = operation.controls[0]
            target = operation.targets[0]
            cells[control] = _symbol_cell("●", cell_width, horizontal)
            cells[target] = _symbol_cell("[X]", cell_width, horizontal)
            low, high = sorted((control, target))
            for qubit in range(low + 1, high):
                cells[qubit] = _symbol_cell("│", cell_width, horizontal)
        for qubit, cell in enumerate(cells):
            lanes[qubit].append(cell)

    return "\n".join("".join(parts) for parts in lanes)


def _operation_cell_width(opcode: OpCode) -> int:
    if opcode in _SINGLE_QUBIT_OPCODES:
        return max(5, len(opcode.value) + 4)
    return 5


def _symbol_cell(symbol: str, width: int, horizontal: str) -> str:
    padding = width - len(symbol)
    left = padding // 2
    right = padding - left
    return horizontal * left + symbol + horizontal * right
