from __future__ import annotations

from dataclasses import dataclass

from ariadion_core import (
    ClassicalBitId,
    LogicalQubitId,
    canonical_json,
    require_nonempty_identifier,
)
from ariadion_ir import CircuitIR
from ariadion_language import Program
from ariadion_semantics import (
    LogicalModule,
    LogicalProgram,
    ReturnShape,
    UnboundQuantumParameterError,
)
from ariadion_simulator import (
    SampledExecutionRequest,
    SampledSimulationResult,
    SimulationExecution,
    SimulationResult,
    simulate,
)
from ariadion_visualization import render_circuit
from daidalon import (
    LogicalCompilationResult,
    compile_logical_module,
    compile_logical_program,
    compile_program,
)
from theonoe import StateReport, inspect_amplitudes, inspect_state, render_report

from .trace import (
    ExactClassicalDistribution,
    ExecutionMode,
    ExecutionTrace,
    MeasurementBitOrder,
    ProbabilityScope,
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
class SampledRunResult:
    """Sampled builder-program execution without an overloaded exact state report."""

    ir: CircuitIR
    simulation: SampledSimulationResult
    circuit: str
    trace: ExecutionTrace | None = None

    def __post_init__(self) -> None:
        if self.simulation.circuit != self.ir:
            raise ValueError("sampled run simulation circuit must match compiled IR")
        if self.trace is not None:
            if self.trace.circuit_id != self.ir.id:
                raise ValueError("sampled run trace must match compiled IR")
            if self.trace.metadata.mode is not ExecutionMode.SAMPLED:
                raise ValueError("sampled run trace must use sampled execution mode")


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
class SampledShot:
    """One public joint classical outcome in ordered result-leaf order."""

    index: int
    outcomes: tuple[int, ...]

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError("sampled shot index must be a non-negative integer")
        if not isinstance(self.outcomes, tuple) or any(
            isinstance(bit, bool) or not isinstance(bit, int) or bit not in {0, 1}
            for bit in self.outcomes
        ):
            raise ValueError("sampled shot outcomes must be a tuple of bits")

    def to_dict(self) -> dict[str, object]:
        return {"index": self.index, "outcomes": list(self.outcomes)}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class SampledClassicalResult:
    """Empirical joint classical outcomes from independently reinitialized shots."""

    result_ids: tuple[ClassicalBitId, ...]
    shots: tuple[SampledShot, ...]
    counts: tuple[int, ...]
    bit_order: MeasurementBitOrder = MeasurementBitOrder.TARGETS_LSB_FIRST
    seed: int | None = None
    scope: ProbabilityScope = ProbabilityScope.JOINT_RETURN

    def __post_init__(self) -> None:
        if not isinstance(self.result_ids, tuple):
            raise ValueError("sampled classical result result_ids must be a tuple")
        for result_id in self.result_ids:
            require_nonempty_identifier(result_id, label="sampled classical result ID")
        if len(self.result_ids) != len(set(self.result_ids)):
            raise ValueError("sampled classical result IDs must be unique")
        if not isinstance(self.shots, tuple) or not self.shots or not all(
            isinstance(shot, SampledShot) for shot in self.shots
        ):
            raise ValueError("sampled classical result shots must be a non-empty tuple")
        if tuple(shot.index for shot in self.shots) != tuple(range(len(self.shots))):
            raise ValueError("sampled classical shot indexes must be contiguous from zero")
        if any(len(shot.outcomes) != len(self.result_ids) for shot in self.shots):
            raise ValueError("sampled shot outcomes must match the declared result IDs")
        if not isinstance(self.counts, tuple) or len(self.counts) != 1 << len(self.result_ids):
            raise ValueError("sampled classical counts must contain one entry per joint outcome")
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in self.counts
        ):
            raise ValueError("sampled classical counts must be non-negative integers")
        if sum(self.counts) != len(self.shots):
            raise ValueError("sampled classical counts must sum to the number of shots")
        if not isinstance(self.bit_order, MeasurementBitOrder):
            raise ValueError("sampled classical bit_order must be MeasurementBitOrder")
        if self.scope is not ProbabilityScope.JOINT_RETURN:
            raise ValueError("sampled classical results must use joint return probability scope")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("sampled classical seed must be an integer or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "result_ids": list(self.result_ids),
            "shots": [shot.to_dict() for shot in self.shots],
            "counts": list(self.counts),
            "bit_order": self.bit_order.value,
            "seed": self.seed,
            "scope": self.scope.value,
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


@dataclass(frozen=True, slots=True)
class SampledLogicalRunResult:
    """Sampled logical execution with empirical outputs, not exact probabilities."""

    compilation: LogicalCompilationResult
    simulation: SampledSimulationResult
    classical_output: SampledClassicalResult | None
    return_shape: ReturnShape
    circuit: str
    trace: ExecutionTrace | None = None

    def __post_init__(self) -> None:
        if self.simulation.circuit != self.compilation.ir:
            raise ValueError("sampled logical simulation circuit must match compiled IR")
        if self.return_shape != self.compilation.readout.return_shape:
            raise ValueError("sampled logical return_shape must match compiled readout")
        if self.compilation.readout.quantum_return_ids():
            raise ValueError(
                "sampled logical execution does not expose single retained quantum handles"
            )
        classical_return_ids = self.compilation.readout.classical_return_ids()
        if classical_return_ids:
            if self.classical_output is None:
                raise ValueError(
                    "sampled logical classical returns require sampled classical output"
                )
            if self.classical_output.result_ids != classical_return_ids:
                raise ValueError(
                    "sampled logical classical output IDs must match classical return leaves"
                )
            if len(self.classical_output.shots) != len(self.simulation.shots):
                raise ValueError(
                    "sampled logical output shots must match sampled simulation shots"
                )
        elif self.classical_output is not None:
            raise ValueError(
                "sampled logical runs without classical returns cannot expose classical output"
            )
        if self.trace is not None:
            if self.trace.circuit_id != self.compilation.ir.id:
                raise ValueError("sampled logical trace must match compiled IR")
            if self.trace.metadata.mode is not ExecutionMode.SAMPLED:
                raise ValueError("sampled logical trace must use sampled execution mode")
            if len(self.simulation.shots) != 1:
                raise ValueError("sampled logical traces require exactly one shot")
            if self.trace.final_state.amplitudes != self.simulation.shots[0].result.amplitudes:
                raise ValueError("sampled logical trace must retain the executed trajectory state")


def run_program(
    program: Program,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: SampledExecutionRequest | None = None,
) -> RunResult | SampledRunResult:
    ir = compile_program(program)
    if execution is not None:
        simulation, execution_trace = _sampled_simulation(
            ir,
            execution=execution,
            trace=trace,
        )
        return SampledRunResult(
            ir=ir,
            simulation=simulation,
            circuit=render_circuit(ir),
            trace=execution_trace,
        )
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
    execution: SampledExecutionRequest | None = None,
) -> LogicalRunResult | SampledLogicalRunResult:
    """Compile and execute logical observations in exact or sampled mode."""

    if program.parameters:
        raise UnboundQuantumParameterError(program.parameters)
    compilation = compile_logical_program(program)
    return _run_logical_compilation(compilation, trace=trace, execution=execution)


def run_logical_module(
    module: LogicalModule,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: SampledExecutionRequest | None = None,
) -> LogicalRunResult | SampledLogicalRunResult:
    """Compile and execute a call-resolved module without binding root parameters."""

    if module.entry_program.parameters:
        raise UnboundQuantumParameterError(module.entry_program.parameters)
    compilation = compile_logical_module(module)
    return _run_logical_compilation(compilation, trace=trace, execution=execution)


def _run_logical_compilation(
    compilation: LogicalCompilationResult,
    *,
    trace: TraceCaptureOptions | None,
    execution: SampledExecutionRequest | None,
) -> LogicalRunResult | SampledLogicalRunResult:
    """Execute one already allocated logical compilation result."""

    if execution is not None:
        if compilation.readout.quantum_return_ids():
            raise ValueError(
                "sampled logical execution does not expose single retained quantum handles"
            )
        simulation, execution_trace = _sampled_simulation(
            compilation.ir,
            execution=execution,
            trace=trace,
        )
        return SampledLogicalRunResult(
            compilation=compilation,
            simulation=simulation,
            classical_output=_sampled_classical_output(compilation, simulation),
            return_shape=compilation.readout.return_shape,
            circuit=render_circuit(compilation.ir),
            trace=execution_trace,
        )

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


def _sampled_simulation(
    circuit: CircuitIR,
    *,
    execution: SampledExecutionRequest,
    trace: TraceCaptureOptions | None,
) -> tuple[SampledSimulationResult, ExecutionTrace | None]:
    execution_trace = None
    if trace is not None and trace.enabled:
        captured_execution = simulate(circuit, execution=execution, trace=trace)
        if not isinstance(captured_execution, SimulationExecution):  # pragma: no cover
            raise RuntimeError("sampled trace-enabled simulation did not return capture data")
        simulation = captured_execution.result
        execution_trace = captured_execution.trace
        if not isinstance(simulation, SampledSimulationResult):  # pragma: no cover
            raise RuntimeError("sampled simulation did not return sampled trajectory data")
        if not isinstance(execution_trace, ExecutionTrace):  # pragma: no cover
            raise RuntimeError("sampled simulation did not return an execution trace")
    else:
        simulation = simulate(circuit, execution=execution)
        if not isinstance(simulation, SampledSimulationResult):  # pragma: no cover
            raise RuntimeError("sampled simulation did not return sampled trajectory data")
    return simulation, execution_trace


def _sampled_classical_output(
    compilation: LogicalCompilationResult,
    simulation: SampledSimulationResult,
) -> SampledClassicalResult | None:
    result_ids = compilation.readout.classical_return_ids()
    if not result_ids:
        return None
    operation_ids_by_result = {
        operation.observation.result_id: operation.id
        for operation in compilation.ir.operations
        if operation.observation is not None
    }
    operation_ids = tuple(
        operation_ids_by_result.get(result_id)
        for result_id in result_ids
    )
    if any(operation_id is None for operation_id in operation_ids):
        raise RuntimeError(
            "compiled readout has a classical return without a lowered observation operation"
        )

    counts = [0] * (1 << len(result_ids))
    shots: list[SampledShot] = []
    for simulated_shot in simulation.shots:
        outcomes_by_operation = {
            outcome.operation_id: outcome.outcome
            for outcome in simulated_shot.measurement_outcomes
        }
        outcome_bits: list[int] = []
        for operation_id in operation_ids:
            assert operation_id is not None
            outcome = outcomes_by_operation.get(operation_id)
            if outcome is None or len(outcome) != 1:
                raise RuntimeError(
                    "sampled logical observation did not produce one required outcome bit"
                )
            outcome_bits.append(outcome[0])
        shot = SampledShot(simulated_shot.index, tuple(outcome_bits))
        shots.append(shot)
        outcome_index = sum(bit << index for index, bit in enumerate(shot.outcomes))
        counts[outcome_index] += 1
    return SampledClassicalResult(
        result_ids=result_ids,
        shots=tuple(shots),
        counts=tuple(counts),
        seed=simulation.seed,
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
