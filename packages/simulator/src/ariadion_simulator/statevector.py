from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from ariadion_ir import CircuitIR, OpCode


@dataclass(frozen=True, slots=True)
class SimulationResult:
    circuit: CircuitIR
    amplitudes: tuple[complex, ...]

    @property
    def probabilities(self) -> tuple[float, ...]:
        return tuple(abs(value) ** 2 for value in self.amplitudes)


def simulate(circuit: CircuitIR) -> SimulationResult:
    size = 1 << circuit.qubit_count
    state = [0j] * size
    state[0] = 1 + 0j

    for operation in circuit.operations:
        if operation.opcode is OpCode.X:
            _apply_single(state, operation.targets[0], 0j, 1 + 0j, 1 + 0j, 0j)
        elif operation.opcode is OpCode.H:
            scale = 1 / sqrt(2)
            _apply_single(state, operation.targets[0], scale, scale, scale, -scale)
        elif operation.opcode is OpCode.Z:
            _apply_single(state, operation.targets[0], 1 + 0j, 0j, 0j, -1 + 0j)
        elif operation.opcode is OpCode.CX:
            _apply_cx(state, operation.controls[0], operation.targets[0])
        elif operation.opcode is OpCode.MEASURE:
            # The reference simulator keeps the full state. Measurement sampling and
            # collapse will be introduced with explicit runtime policies.
            continue
        else:  # pragma: no cover - protects future enum expansion
            raise ValueError(f"unsupported opcode: {operation.opcode}")

    return SimulationResult(circuit, tuple(state))


def _apply_single(
    state: list[complex],
    target: int,
    m00: complex,
    m01: complex,
    m10: complex,
    m11: complex,
) -> None:
    mask = 1 << target
    for base in range(len(state)):
        if base & mask:
            continue
        partner = base | mask
        zero, one = state[base], state[partner]
        state[base] = m00 * zero + m01 * one
        state[partner] = m10 * zero + m11 * one


def _apply_cx(state: list[complex], control: int, target: int) -> None:
    control_mask = 1 << control
    target_mask = 1 << target
    for base in range(len(state)):
        if not (base & control_mask) or (base & target_mask):
            continue
        partner = base | target_mask
        state[base], state[partner] = state[partner], state[base]
