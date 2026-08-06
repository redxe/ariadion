from __future__ import annotations

from dataclasses import dataclass

from ariadion_ir import CircuitIR
from ariadion_language import Program
from ariadion_simulator import SimulationResult, simulate
from ariadion_visualization import render_circuit
from daidalon import compile_program
from theonoe import StateReport, inspect_state, render_report


@dataclass(frozen=True, slots=True)
class RunResult:
    ir: CircuitIR
    simulation: SimulationResult
    inspection: StateReport
    circuit: str
    report: str


def run_program(program: Program) -> RunResult:
    ir = compile_program(program)
    simulation = simulate(ir)
    inspection = inspect_state(simulation)
    return RunResult(
        ir=ir,
        simulation=simulation,
        inspection=inspection,
        circuit=render_circuit(ir),
        report=render_report(inspection),
    )
