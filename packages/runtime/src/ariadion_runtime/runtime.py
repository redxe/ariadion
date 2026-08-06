from __future__ import annotations

from dataclasses import dataclass

from ariadion_core import (
    LogicalQubitId,
    canonical_json,
    require_nonempty_identifier,
)
from ariadion_ir import CircuitIR
from ariadion_language import Program
from ariadion_semantics import LogicalProgram, ReturnShape
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
class ReturnedQuantumValue:
    """A logical handle into the retained returned state-vector, not a copied state."""

    logical_qubit_id: LogicalQubitId
    allocated_slot: int
    display_name: str | None

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.logical_qubit_id,
            label="returned quantum logical qubit ID",
        )
        if (
            isinstance(self.allocated_slot, bool)
            or not isinstance(self.allocated_slot, int)
            or self.allocated_slot < 0
        ):
            raise ValueError("returned quantum allocated_slot must be a non-negative integer")
        if self.display_name is not None:
            require_nonempty_identifier(
                self.display_name,
                label="returned quantum display name",
            )

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "logical_qubit_id": self.logical_qubit_id,
            "allocated_slot": self.allocated_slot,
            "display_name": self.display_name,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class LogicalRunResult:
    """Exact execution artifacts for structured classical and quantum returns."""

    compilation: LogicalCompilationResult
    simulation: SimulationResult
    pre_observation_state: StateSnapshot
    classical_output_distribution: ExactClassicalDistribution | None
    returned_quantum_values: tuple[ReturnedQuantumValue, ...]
    return_shape: ReturnShape
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
        if self.return_shape != self.compilation.readout.return_shape:
            raise ValueError("logical run return_shape must match compiled readout")
        if not isinstance(self.returned_quantum_values, tuple) or not all(
            isinstance(value, ReturnedQuantumValue) for value in self.returned_quantum_values
        ):
            raise ValueError(
                "logical run returned_quantum_values must contain ReturnedQuantumValue values"
            )
        classical_return_ids = self.compilation.readout.classical_return_ids()
        if classical_return_ids:
            if self.classical_output_distribution is None:
                raise ValueError(
                    "logical run classical returns require an exact classical distribution"
                )
            if self.classical_output_distribution.result_ids != classical_return_ids:
                raise ValueError(
                    "logical run classical distribution IDs must match classical return leaves"
                )
        elif self.classical_output_distribution is not None:
            raise ValueError(
                "logical run without classical returns cannot expose a classical distribution"
            )
        quantum_return_ids = self.compilation.readout.quantum_return_ids()
        if tuple(value.logical_qubit_id for value in self.returned_quantum_values) != (
            quantum_return_ids
        ):
            raise ValueError(
                "logical run quantum handles must match quantum return leaves"
            )


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
        returned_quantum_values=_returned_quantum_values(compilation),
        return_shape=compilation.readout.return_shape,
        pre_observation_inspection=pre_observation_inspection,
        circuit=render_circuit(compilation.ir),
        report=render_report(pre_observation_inspection),
        trace=execution_trace,
    )


def _exact_classical_output_distribution(
    compilation: LogicalCompilationResult,
    simulation: SimulationResult,
) -> ExactClassicalDistribution | None:
    observations_by_result = {
        observation.result_id: observation
        for observation in compilation.readout.observations
    }
    result_ids = compilation.readout.classical_return_ids()
    if not result_ids:
        return None
    slots: list[int] = []
    for result_id in result_ids:
        observation = observations_by_result.get(result_id)
        if observation is None:
            raise RuntimeError(
                "compiled readout has a classical return without a lowered observation: "
                f"{result_id}"
            )
        slots.append(observation.allocated_slot)

    probabilities = [0.0] * (1 << len(result_ids))
    for basis_index, amplitude in enumerate(simulation.amplitudes):
        outcome = 0
        for outcome_bit, slot in enumerate(slots):
            if basis_index & (1 << slot):
                outcome |= 1 << outcome_bit
        probabilities[outcome] += abs(amplitude) ** 2
    return ExactClassicalDistribution(result_ids, tuple(probabilities))


def _returned_quantum_values(
    compilation: LogicalCompilationResult,
) -> tuple[ReturnedQuantumValue, ...]:
    allocation_entries = {
        entry.logical_qubit_id: entry
        for entry in compilation.logical_allocation.entries
    }
    returned_values: list[ReturnedQuantumValue] = []
    for logical_qubit_id in compilation.readout.quantum_return_ids():
        entry = allocation_entries.get(logical_qubit_id)
        if entry is None:  # pragma: no cover - guarded by LogicalCompilationResult
            raise RuntimeError(
                "compiled readout has a quantum return without an allocated logical slot: "
                f"{logical_qubit_id}"
            )
        returned_values.append(
            ReturnedQuantumValue(
                logical_qubit_id=logical_qubit_id,
                allocated_slot=entry.slot,
                display_name=entry.display_name,
            )
        )
    return tuple(returned_values)
