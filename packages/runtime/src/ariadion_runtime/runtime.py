from __future__ import annotations

from dataclasses import dataclass

from ariadion_core import ClassicalBitId
from ariadion_ir import CircuitIR
from ariadion_language import Program
from ariadion_semantics import LogicalProgram
from ariadion_simulator import (
    SimulationExecution,
    SimulationResult,
    simulate,
)
from ariadion_visualization import render_circuit
from daidalon import LogicalCompilationResult, compile_logical_program, compile_program
from theonoe import StateReport, inspect_amplitudes, inspect_state, render_report

from .trace import (
    ExactClassicalDistribution,
    ExecutionTrace,
    StateSnapshot,
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


@dataclass(frozen=True, slots=True)
class LogicalRunResult:
    """Exact terminal execution artifacts for one compiled logical program."""

    compilation: LogicalCompilationResult
    simulation: SimulationResult
    pre_observation_state: StateSnapshot
    classical_output_distribution: ExactClassicalDistribution
    pre_observation_inspection: StateReport
    circuit: str
    report: str
    trace: ExecutionTrace | None = None

    def __post_init__(self) -> None:
        if self.simulation.circuit != self.compilation.ir:
            raise ValueError("logical run simulation circuit must match compiled IR")
        if self.pre_observation_state.circuit_id != self.compilation.ir.id:
            raise ValueError("logical run pre_observation_state must match compiled IR")
        if self.pre_observation_state.amplitudes != self.simulation.amplitudes:
            raise ValueError(
                "logical run pre_observation_state must retain exact simulation amplitudes"
            )
        if self.pre_observation_inspection.qubit_count != self.compilation.ir.qubit_count:
            raise ValueError(
                "logical run pre_observation_inspection must match compiled IR width"
            )
        if self.trace is not None and self.trace.circuit_id != self.compilation.ir.id:
            raise ValueError("logical run trace must match compiled IR")


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


def run_logical_program(
    program: LogicalProgram,
    *,
    trace: TraceCaptureOptions | None = None,
) -> LogicalRunResult:
    """Compile and execute terminal logical observations without sampled collapse."""

    compilation = compile_logical_program(program)
    execution_trace = None
    if trace is not None and trace.enabled:
        captured_execution = simulate(compilation.ir, trace=trace)
        if not isinstance(captured_execution, SimulationExecution):  # pragma: no cover
            raise RuntimeError("trace-enabled simulation did not return capture data")
        simulation = captured_execution.result
        execution_trace = captured_execution.trace
        if not isinstance(execution_trace, ExecutionTrace):  # pragma: no cover
            raise RuntimeError("trace-enabled simulation did not return an execution trace")
    else:
        simulation = simulate(compilation.ir)
    pre_observation_state = StateSnapshot(
        compilation.ir.id,
        compilation.ir.qubit_count,
        simulation.amplitudes,
    )
    pre_observation_inspection = inspect_amplitudes(
        pre_observation_state.amplitudes,
        pre_observation_state.qubit_count,
    )
    return LogicalRunResult(
        compilation=compilation,
        simulation=simulation,
        pre_observation_state=pre_observation_state,
        classical_output_distribution=_exact_classical_output_distribution(compilation, simulation),
        pre_observation_inspection=pre_observation_inspection,
        circuit=render_circuit(compilation.ir),
        report=render_report(pre_observation_inspection),
        trace=execution_trace,
    )


def _exact_classical_output_distribution(
    compilation: LogicalCompilationResult,
    simulation: SimulationResult,
) -> ExactClassicalDistribution:
    observations_by_result = {
        str(observation.result_id): observation
        for observation in compilation.readout.observations
    }
    result_ids: list[ClassicalBitId] = []
    slots: list[int] = []
    for output in compilation.readout.output_order:
        observation = observations_by_result.get(str(output))
        if observation is None:
            continue
        result_ids.append(ClassicalBitId(str(output)))
        slots.append(observation.allocated_slot)

    probabilities = [0.0] * (1 << len(result_ids))
    for basis_index, amplitude in enumerate(simulation.amplitudes):
        outcome = 0
        for outcome_bit, slot in enumerate(slots):
            if basis_index & (1 << slot):
                outcome |= 1 << outcome_bit
        probabilities[outcome] += abs(amplitude) ** 2
    return ExactClassicalDistribution(tuple(result_ids), tuple(probabilities))
