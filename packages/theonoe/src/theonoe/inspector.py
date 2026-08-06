from __future__ import annotations

import cmath
from dataclasses import dataclass

from ariadion_simulator import SimulationResult


@dataclass(frozen=True, slots=True)
class BasisState:
    label: str
    amplitude: complex
    probability: float
    phase_radians: float


@dataclass(frozen=True, slots=True)
class StateReport:
    qubit_count: int
    states: tuple[BasisState, ...]
    entangled_qubits: tuple[int, ...]


def inspect_state(result: SimulationResult, *, epsilon: float = 1e-12) -> StateReport:
    width = result.circuit.qubit_count
    states = []
    for index, amplitude in enumerate(result.amplitudes):
        probability = abs(amplitude) ** 2
        if probability <= epsilon:
            continue
        states.append(
            BasisState(
                label=f"|{index:0{width}b}>",
                amplitude=amplitude,
                probability=probability,
                phase_radians=cmath.phase(amplitude),
            )
        )

    entangled = tuple(
        qubit
        for qubit in range(width)
        if _single_qubit_purity(result.amplitudes, width, qubit) < 1 - 1e-9
    )
    return StateReport(width, tuple(states), entangled)


def render_report(report: StateReport) -> str:
    lines = ["Theonoe state report", "--------------------"]
    for state in report.states:
        lines.append(
            f"{state.label:<8} p={state.probability:.6f} "
            f"amp={_format_complex(state.amplitude)} phase={state.phase_radians:+.6f} rad"
        )
    if report.entangled_qubits:
        qubits = ", ".join(f"q{index}" for index in report.entangled_qubits)
        lines.append(f"entanglement hint: mixed reduced states detected for {qubits}")
    else:
        lines.append("entanglement hint: none detected")
    return "\n".join(lines)


def _single_qubit_purity(amplitudes: tuple[complex, ...], width: int, target: int) -> float:
    # Reduced density matrix for one qubit, calculated directly from amplitudes.
    mask = 1 << target
    rho00 = 0j
    rho11 = 0j
    rho01 = 0j
    for base in range(1 << width):
        if base & mask:
            continue
        partner = base | mask
        a0, a1 = amplitudes[base], amplitudes[partner]
        rho00 += a0 * a0.conjugate()
        rho11 += a1 * a1.conjugate()
        rho01 += a0 * a1.conjugate()
    rho10 = rho01.conjugate()
    purity = rho00 * rho00 + rho11 * rho11 + 2 * rho01 * rho10
    return float(purity.real)


def _format_complex(value: complex) -> str:
    return f"{value.real:+.6f}{value.imag:+.6f}i"
