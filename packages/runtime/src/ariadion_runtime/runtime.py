from __future__ import annotations

from dataclasses import dataclass

from ariadion_ir import CircuitIR
from ariadion_language import Program
from ariadion_simulator import (
    SimulationExecution,
    SimulationResult,
    simulate,
)
from ariadion_visualization import render_circuit
from daidalon import compile_program
from theonoe import StateReport, inspect_state, render_report

from .trace import (
    ExecutionTrace,
    TraceCaptureOptions,
)


@dataclass(frozen=True, slots=True)
class RunResult:
    ir: CircuitIR
    simulation: SimulationResult
    inspection: StateReport
    circuit: str
    report: str
    trace: ExecutionTrace | None = None


def run_program(
    program: Program,
    *,
    trace: TraceCaptureOptions | None = None,
) -> RunResult:
    ir = compile_program(program)
    execution_trace = None
    if trace is not None and trace.enabled:
        captured_execution = simulate(ir, trace=trace)
        if not isinstance(captured_execution, SimulationExecution):  # pragma: no cover
            raise RuntimeError("trace-enabled simulation did not return capture data")
        simulation = captured_execution.result
        execution_trace = captured_execution.trace
        if not isinstance(execution_trace, ExecutionTrace):  # pragma: no cover
            raise RuntimeError("trace-enabled simulation did not return an execution trace")
    else:
        simulation = simulate(ir)
    inspection = inspect_state(simulation)
    return RunResult(
        ir=ir,
        simulation=simulation,
        inspection=inspection,
        circuit=render_circuit(ir),
        report=render_report(inspection),
        trace=execution_trace,
    )
