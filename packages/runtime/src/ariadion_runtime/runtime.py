from __future__ import annotations

from dataclasses import dataclass

from ariadion_core import (
    ClassicalBitId,
    LogicalQubitId,
    ProgramId,
    canonical_json,
    require_nonempty_identifier,
)
from ariadion_ir import CircuitIR
from ariadion_language import Program
from ariadion_noise import BinaryReadoutChannel, GateChannelBinding, IdleDecoherenceProfile
from ariadion_semantics import (
    LogicalModule,
    LogicalProgram,
    ReturnShape,
    UnboundQuantumParameterError,
)
from ariadion_simulator import (
    DensityMatrixExecutionRequest,
    DensityMatrixResult,
    GateNoiseApplicationEvent,
    IdleDecoherenceEvent,
    SampledExecutionRequest,
    SampledSimulationResult,
    SimulationExecution,
    SimulationResult,
    ValidatedDensityState,
    simulate,
    simulate_density_matrix,
)
from ariadion_visualization import render_circuit
from daidalon import (
    LogicalCompilationResult,
    compile_logical_module,
    compile_logical_program,
    compile_program,
)
from theonoe import StateReport, inspect_amplitudes, inspect_state, render_report
from theonoe import (
    BinaryReadoutChannelSnapshot,
    IdleDecoherenceProfileSnapshot,
    NoiseImpactBaselineMode,
    NoiseImpactComparisonProvenance,
    NoiseImpactReport,
    NoiseImpactScheduleSummary,
    build_noise_impact_report,
)

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


class DensityMatrixTraceUnsupportedError(ValueError):
    """Raised when amplitude-only trace capture is requested for a density state."""

    code = "A205"

    def __init__(self) -> None:
        super().__init__(
            f"{self.code}: density-matrix execution does not support amplitude trace capture"
        )


@dataclass(frozen=True, slots=True)
class DensityMatrixRunResult:
    """Exact mixed-state builder-program execution without state-vector inspection."""

    ir: CircuitIR
    simulation: DensityMatrixResult
    circuit: str

    def __post_init__(self) -> None:
        if self.simulation.circuit != self.ir:
            raise ValueError("density-matrix run simulation circuit must match compiled IR")


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


@dataclass(frozen=True, slots=True)
class DensityExecutionScheduleSnapshot:
    """Runtime-owned immutable schedule provenance for density execution."""

    program_id: ProgramId
    operation_fingerprint: tuple[
        tuple[str, str, tuple[int, ...], tuple[int, ...], float | None],
        ...,
    ]
    peak_duration_ns: float

    def __post_init__(self) -> None:
        require_nonempty_identifier(
            self.program_id,
            label="density execution schedule program_id",
        )
        if not isinstance(self.operation_fingerprint, tuple):
            raise ValueError(
                "density execution schedule operation_fingerprint must be a tuple"
            )
        for entry in self.operation_fingerprint:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 5
                or not isinstance(entry[0], str)
                or not isinstance(entry[1], str)
                or not isinstance(entry[2], tuple)
                or not isinstance(entry[3], tuple)
            ):
                raise ValueError(
                    "density execution schedule operation_fingerprint must contain "
                    "(operation_id, opcode, targets, controls, angle_radians) tuples"
                )
            if not all(isinstance(target, int) and target >= 0 for target in entry[2]):
                raise ValueError(
                    "density execution schedule operation_fingerprint targets must be "
                    "non-negative integers"
                )
            if not all(isinstance(control, int) and control >= 0 for control in entry[3]):
                raise ValueError(
                    "density execution schedule operation_fingerprint controls must be "
                    "non-negative integers"
                )
            if entry[4] is not None and not isinstance(entry[4], (int, float)):
                raise ValueError(
                    "density execution schedule operation_fingerprint angle_radians must "
                    "be None or numeric"
                )
        if (
            isinstance(self.peak_duration_ns, bool)
            or not isinstance(self.peak_duration_ns, (int, float))
            or self.peak_duration_ns < 0
        ):
            raise ValueError(
                "density execution schedule peak_duration_ns must be a non-negative number"
            )


@dataclass(frozen=True, slots=True)
class DensityExecutionProvenanceSnapshot:
    """Runtime-owned provenance facts for supported density logical execution."""

    circuit_id: ProgramId
    backend_id: str
    schedule: DensityExecutionScheduleSnapshot | None
    idle_decoherence: IdleDecoherenceProfile | None
    gate_noise_bindings: tuple[GateChannelBinding, ...]
    readout_channel: BinaryReadoutChannel | None
    gate_event_operation_ids: tuple[str, ...]
    idle_event_slots: tuple[int, ...]
    classical_result_ids: tuple[ClassicalBitId, ...]
    physical_distribution_size: int | None
    reported_distribution_size: int | None
    reported_matches_physical: bool | None

    def __post_init__(self) -> None:
        require_nonempty_identifier(self.circuit_id, label="density execution provenance circuit_id")
        require_nonempty_identifier(self.backend_id, label="density execution provenance backend_id")
        if self.schedule is not None and not isinstance(
            self.schedule,
            DensityExecutionScheduleSnapshot,
        ):
            raise ValueError("density execution provenance schedule must be DensityExecutionScheduleSnapshot or None")
        if self.idle_decoherence is not None and not isinstance(
            self.idle_decoherence,
            IdleDecoherenceProfile,
        ):
            raise ValueError(
                "density execution provenance idle_decoherence must be IdleDecoherenceProfile or None"
            )
        if (self.schedule is None) != (self.idle_decoherence is None):
            raise ValueError(
                "density execution provenance schedule and idle_decoherence must be paired"
            )
        if self.schedule is not None and self.schedule.program_id != self.circuit_id:
            raise ValueError(
                "density execution provenance schedule program_id must match circuit_id"
            )
        if not isinstance(self.gate_noise_bindings, tuple) or not all(
            isinstance(binding, GateChannelBinding) for binding in self.gate_noise_bindings
        ):
            raise ValueError(
                "density execution provenance gate_noise_bindings must be GateChannelBinding values"
            )
        if self.readout_channel is not None and not isinstance(
            self.readout_channel,
            BinaryReadoutChannel,
        ):
            raise ValueError(
                "density execution provenance readout_channel must be BinaryReadoutChannel or None"
            )
        if not isinstance(self.gate_event_operation_ids, tuple) or not all(
            isinstance(operation_id, str) and operation_id
            for operation_id in self.gate_event_operation_ids
        ):
            raise ValueError(
                "density execution provenance gate_event_operation_ids must be a tuple of IDs"
            )
        if not isinstance(self.idle_event_slots, tuple) or not all(
            isinstance(slot, int) and slot >= 0 for slot in self.idle_event_slots
        ):
            raise ValueError(
                "density execution provenance idle_event_slots must be non-negative integers"
            )
        if not isinstance(self.classical_result_ids, tuple) or not all(
            isinstance(result_id, str) and result_id for result_id in self.classical_result_ids
        ):
            raise ValueError(
                "density execution provenance classical_result_ids must be a tuple of IDs"
            )
        sizes = (self.physical_distribution_size, self.reported_distribution_size)
        if all(size is None for size in sizes):
            if self.classical_result_ids:
                raise ValueError(
                    "density execution provenance classical_result_ids require distributions"
                )
            if self.reported_matches_physical is not None:
                raise ValueError(
                    "density execution provenance reported_matches_physical must be None when distributions are absent"
                )
        else:
            if any(size is None for size in sizes):
                raise ValueError(
                    "density execution provenance distribution sizes must both be present or both absent"
                )
            assert self.physical_distribution_size is not None
            assert self.reported_distribution_size is not None
            if self.physical_distribution_size <= 0 or self.reported_distribution_size <= 0:
                raise ValueError(
                    "density execution provenance distribution sizes must be positive"
                )
            if self.physical_distribution_size != self.reported_distribution_size:
                raise ValueError(
                    "density execution provenance physical and reported distribution sizes must match"
                )
            if not self.classical_result_ids:
                raise ValueError(
                    "density execution provenance distributions require classical_result_ids"
                )
            if self.reported_matches_physical is None:
                raise ValueError(
                    "density execution provenance reported_matches_physical must be set when distributions are present"
                )


@dataclass(frozen=True, slots=True)
class DensityMatrixLogicalRunResult:
    """Exact mixed-state logical execution with physical and reported readout laws."""

    compilation: LogicalCompilationResult
    simulation: DensityMatrixResult
    provenance: DensityExecutionProvenanceSnapshot
    physical_classical_output_distribution: ExactClassicalDistribution | None
    reported_classical_output_distribution: ExactClassicalDistribution | None
    returned_quantum_values: tuple[ReturnedQuantumValue, ...]
    return_shape: ReturnShape
    circuit: str

    def __post_init__(self) -> None:
        if self.simulation.circuit != self.compilation.ir:
            raise ValueError(
                "density-matrix logical simulation circuit must match compiled IR"
            )
        if not isinstance(self.provenance, DensityExecutionProvenanceSnapshot):
            raise ValueError(
                "density-matrix logical provenance must be DensityExecutionProvenanceSnapshot"
            )
        if self.provenance.circuit_id != self.compilation.ir.id:
            raise ValueError(
                "density-matrix logical provenance circuit_id must match compiled IR"
            )
        if self.provenance.circuit_id != self.simulation.circuit.id:
            raise ValueError(
                "density-matrix logical provenance circuit_id must match simulation circuit"
            )
        if self.provenance.backend_id != "reference-density-matrix":
            raise ValueError(
                "density-matrix logical provenance backend_id must describe the executed reference backend"
            )
        if self.provenance.gate_event_operation_ids != tuple(
            event.operation_id for event in self.simulation.gate_noise_events
        ):
            raise ValueError(
                "density-matrix logical provenance gate_event_operation_ids must match simulation evidence"
            )
        if self.provenance.idle_event_slots != tuple(
            event.slot for event in self.simulation.idle_decoherence_events
        ):
            raise ValueError(
                "density-matrix logical provenance idle_event_slots must match simulation evidence"
            )
        if self.return_shape != self.compilation.readout.return_shape:
            raise ValueError("density-matrix logical return_shape must match compiled readout")
        if not isinstance(self.returned_quantum_values, tuple) or not all(
            isinstance(value, ReturnedQuantumValue) for value in self.returned_quantum_values
        ):
            raise ValueError(
                "density-matrix logical returned_quantum_values must contain "
                "ReturnedQuantumValue values"
            )
        classical_return_ids = self.compilation.readout.classical_return_ids()
        distributions = (
            self.physical_classical_output_distribution,
            self.reported_classical_output_distribution,
        )
        if classical_return_ids:
            if any(distribution is None for distribution in distributions):
                raise ValueError(
                    "density-matrix logical classical returns require physical and "
                    "reported distributions"
                )
            if any(
                distribution is not None and distribution.result_ids != classical_return_ids
                for distribution in distributions
            ):
                raise ValueError(
                    "density-matrix logical distribution IDs must match classical return leaves"
                )
            assert self.physical_classical_output_distribution is not None
            assert self.reported_classical_output_distribution is not None
            distribution_size = len(self.physical_classical_output_distribution.probabilities)
            if self.provenance.physical_distribution_size != distribution_size:
                raise ValueError(
                    "density-matrix logical provenance physical_distribution_size must match physical output"
                )
            if (
                self.provenance.reported_distribution_size
                != len(self.reported_classical_output_distribution.probabilities)
            ):
                raise ValueError(
                    "density-matrix logical provenance reported_distribution_size must match reported output"
                )
            if self.provenance.classical_result_ids != classical_return_ids:
                raise ValueError(
                    "density-matrix logical provenance classical_result_ids must match classical returns"
                )
            if self.provenance.readout_channel is None:
                if (
                    self.reported_classical_output_distribution.probabilities
                    != self.physical_classical_output_distribution.probabilities
                ):
                    raise ValueError(
                        "density-matrix logical reported distribution must equal physical distribution without readout noise"
                    )
            if (
                self.provenance.reported_matches_physical
                != (
                    self.reported_classical_output_distribution.probabilities
                    == self.physical_classical_output_distribution.probabilities
                )
            ):
                raise ValueError(
                    "density-matrix logical provenance reported_matches_physical must match distributions"
                )
        elif any(distribution is not None for distribution in distributions):
            raise ValueError(
                "density-matrix logical runs without classical returns cannot expose "
                "classical distributions"
            )
        else:
            if self.provenance.physical_distribution_size is not None:
                raise ValueError(
                    "density-matrix logical provenance must omit distribution sizes without classical returns"
                )
            if self.provenance.classical_result_ids:
                raise ValueError(
                    "density-matrix logical provenance must omit classical_result_ids without classical returns"
                )
        quantum_return_ids = self.compilation.readout.quantum_return_ids()
        if tuple(value.logical_qubit_id for value in self.returned_quantum_values) != (
            quantum_return_ids
        ):
            raise ValueError(
                "density-matrix logical quantum handles must match quantum return leaves"
            )


def run_program(
    program: Program,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: SampledExecutionRequest | DensityMatrixExecutionRequest | None = None,
) -> RunResult | SampledRunResult | DensityMatrixRunResult:
    ir = compile_program(program)
    if isinstance(execution, DensityMatrixExecutionRequest):
        _reject_density_trace(trace)
        return DensityMatrixRunResult(
            ir=ir,
            simulation=simulate_density_matrix(ir, execution=execution),
            circuit=render_circuit(ir),
        )
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
    execution: SampledExecutionRequest | DensityMatrixExecutionRequest | None = None,
) -> LogicalRunResult | SampledLogicalRunResult | DensityMatrixLogicalRunResult:
    """Compile and execute logical observations in exact or sampled mode."""

    if program.parameters:
        raise UnboundQuantumParameterError(program.parameters)
    compilation = compile_logical_program(program)
    return _run_logical_compilation(compilation, trace=trace, execution=execution)


def run_logical_module(
    module: LogicalModule,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: SampledExecutionRequest | DensityMatrixExecutionRequest | None = None,
) -> LogicalRunResult | SampledLogicalRunResult | DensityMatrixLogicalRunResult:
    """Compile and execute a call-resolved module without binding root parameters."""

    if module.entry_program.parameters:
        raise UnboundQuantumParameterError(module.entry_program.parameters)
    compilation = compile_logical_module(module)
    return _run_logical_compilation(compilation, trace=trace, execution=execution)


def _run_logical_compilation(
    compilation: LogicalCompilationResult,
    *,
    trace: TraceCaptureOptions | None,
    execution: SampledExecutionRequest | DensityMatrixExecutionRequest | None,
) -> LogicalRunResult | SampledLogicalRunResult | DensityMatrixLogicalRunResult:
    """Execute one already allocated logical compilation result."""

    if isinstance(execution, DensityMatrixExecutionRequest):
        _reject_density_trace(trace)
        simulation = simulate_density_matrix(compilation.ir, execution=execution)
        physical_distribution, reported_distribution = _density_classical_output_distributions(
            compilation,
            simulation,
            readout_channel=execution.noise_model.readout_channel,
        )
        provenance = _build_density_execution_provenance(
            compilation=compilation,
            simulation=simulation,
            execution=execution,
            physical_distribution=physical_distribution,
            reported_distribution=reported_distribution,
        )
        return DensityMatrixLogicalRunResult(
            compilation=compilation,
            simulation=simulation,
            provenance=provenance,
            physical_classical_output_distribution=physical_distribution,
            reported_classical_output_distribution=reported_distribution,
            returned_quantum_values=_returned_quantum_values(compilation),
            return_shape=compilation.readout.return_shape,
            circuit=render_circuit(compilation.ir),
        )

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


def build_density_noise_impact_report(
    run: DensityMatrixLogicalRunResult,
) -> NoiseImpactReport:
    """Build an inspectable ideal-vs-noisy-vs-reported density noise-impact report."""

    if not isinstance(run, DensityMatrixLogicalRunResult):
        raise ValueError("density noise-impact reporting requires DensityMatrixLogicalRunResult")

    reference_backend_id = "reference-density-matrix"
    if run.provenance.backend_id != reference_backend_id:
        raise ValueError(
            "density noise-impact reporting currently supports reference-density-matrix provenance only"
        )

    ideal_simulation = simulate_density_matrix(run.compilation.ir)
    ideal_physical_distribution, _ = _density_classical_output_distributions(
        run.compilation,
        ideal_simulation,
        readout_channel=None,
    )

    ideal_probabilities: tuple[float, ...] | None = (
        ideal_physical_distribution.probabilities
        if ideal_physical_distribution is not None
        else None
    )
    noisy_physical_probabilities: tuple[float, ...] | None = (
        run.physical_classical_output_distribution.probabilities
        if run.physical_classical_output_distribution is not None
        else None
    )
    reported_probabilities: tuple[float, ...] | None = (
        run.reported_classical_output_distribution.probabilities
        if run.reported_classical_output_distribution is not None
        else None
    )
    schedule = run.provenance.schedule
    schedule_summary = (
        NoiseImpactScheduleSummary(
            program_id=schedule.program_id,
            operation_fingerprint=schedule.operation_fingerprint,
            peak_duration_ns=schedule.peak_duration_ns,
        )
        if schedule is not None
        else None
    )

    return build_noise_impact_report(
        comparison=NoiseImpactComparisonProvenance(
            circuit_id=run.compilation.ir.id,
            representation="density_matrix",
            noisy_backend_id=reference_backend_id,
            ideal_backend_id=reference_backend_id,
            ideal_baseline_mode=NoiseImpactBaselineMode.IDEAL_NOISE_DISABLED_REPLAY,
            noisy_schedule=schedule_summary,
            noisy_idle_decoherence=(
                IdleDecoherenceProfileSnapshot(
                    t1_ns=run.provenance.idle_decoherence.t1_ns,
                    t2_ns=run.provenance.idle_decoherence.t2_ns,
                )
                if run.provenance.idle_decoherence is not None
                else None
            ),
            ideal_baseline_derivation=(
                "ideal baseline re-executed on the same compiled circuit with "
                "executable noise disabled; schedule-dependent idle decoherence is "
                "not executed during ideal replay"
            ),
        ),
        ideal_density_matrix=ValidatedDensityState(
            density_matrix=ideal_simulation.density_matrix,
            qubit_count=run.compilation.ir.qubit_count,
        ),
        noisy_density_matrix=ValidatedDensityState(
            density_matrix=run.simulation.density_matrix,
            qubit_count=run.compilation.ir.qubit_count,
        ),
        ideal_physical_distribution=ideal_probabilities,
        noisy_physical_distribution=noisy_physical_probabilities,
        reported_distribution=reported_probabilities,
        idle_events=run.simulation.idle_decoherence_events,
        gate_events=run.simulation.gate_noise_events,
        readout_channel=(
            BinaryReadoutChannelSnapshot(
                p_one_given_zero=run.provenance.readout_channel.p_one_given_zero,
                p_zero_given_one=run.provenance.readout_channel.p_zero_given_one,
            )
            if run.provenance.readout_channel is not None
            else None
        ),
    )


def _build_density_execution_provenance(
    *,
    compilation: LogicalCompilationResult,
    simulation: DensityMatrixResult,
    execution: DensityMatrixExecutionRequest,
    physical_distribution: ExactClassicalDistribution | None,
    reported_distribution: ExactClassicalDistribution | None,
) -> DensityExecutionProvenanceSnapshot:
    if simulation.circuit.id != compilation.ir.id:
        raise ValueError("density execution provenance simulation circuit must match compilation IR")
    schedule_snapshot = (
        DensityExecutionScheduleSnapshot(
            program_id=execution.schedule.program_id,
            operation_fingerprint=execution.schedule.operation_fingerprint,
            peak_duration_ns=execution.schedule.peak_duration_ns,
        )
        if execution.schedule is not None
        else None
    )
    readout_channel = execution.noise_model.readout_channel
    if (physical_distribution is None) != (reported_distribution is None):
        raise ValueError(
            "density execution provenance requires physical and reported distributions to be paired"
        )
    if physical_distribution is None:
        classical_result_ids: tuple[ClassicalBitId, ...] = ()
        physical_size: int | None = None
        reported_size: int | None = None
        reported_matches: bool | None = None
    else:
        assert reported_distribution is not None
        if physical_distribution.result_ids != reported_distribution.result_ids:
            raise ValueError(
                "density execution provenance requires matching physical and reported result IDs"
            )
        classical_result_ids = physical_distribution.result_ids
        physical_size = len(physical_distribution.probabilities)
        reported_size = len(reported_distribution.probabilities)
        reported_matches = (
            physical_distribution.probabilities == reported_distribution.probabilities
        )
        if readout_channel is None and not reported_matches:
            raise ValueError(
                "density execution provenance requires matching physical and reported "
                "distributions when readout_channel is absent"
            )

    gate_event_operation_ids = tuple(
        event.operation_id for event in simulation.gate_noise_events
    )
    idle_event_slots = tuple(event.slot for event in simulation.idle_decoherence_events)

    return DensityExecutionProvenanceSnapshot(
        circuit_id=compilation.ir.id,
        backend_id="reference-density-matrix",
        schedule=schedule_snapshot,
        idle_decoherence=execution.idle_decoherence,
        gate_noise_bindings=execution.noise_model.gate_channels,
        readout_channel=readout_channel,
        gate_event_operation_ids=gate_event_operation_ids,
        idle_event_slots=idle_event_slots,
        classical_result_ids=classical_result_ids,
        physical_distribution_size=physical_size,
        reported_distribution_size=reported_size,
        reported_matches_physical=reported_matches,
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


def _reject_density_trace(trace: TraceCaptureOptions | None) -> None:
    if trace is not None and trace.enabled:
        raise DensityMatrixTraceUnsupportedError()


def _density_classical_output_distributions(
    compilation: LogicalCompilationResult,
    simulation: DensityMatrixResult,
    *,
    readout_channel: BinaryReadoutChannel | None,
) -> tuple[ExactClassicalDistribution | None, ExactClassicalDistribution | None]:
    """Project density diagonals and apply readout once per distinct observation."""

    result_ids = compilation.readout.classical_return_ids()
    if not result_ids:
        return None, None
    observations_by_result = {
        observation.result_id: observation for observation in compilation.readout.observations
    }
    unique_result_ids = tuple(dict.fromkeys(result_ids))
    slots: list[int] = []
    for result_id in unique_result_ids:
        observation = observations_by_result.get(result_id)
        if observation is None:
            raise RuntimeError(
                "compiled readout has a classical return without a lowered observation: "
                f"{result_id}"
            )
        slots.append(observation.allocated_slot)

    unique_probabilities = _density_joint_probabilities(simulation, tuple(slots))
    leaf_indexes = tuple(unique_result_ids.index(result_id) for result_id in result_ids)
    physical = ExactClassicalDistribution(
        result_ids,
        _project_unique_probabilities(unique_probabilities, leaf_indexes),
    )
    if readout_channel is None:
        return physical, physical
    reported_unique_probabilities = _apply_binary_readout(
        unique_probabilities,
        bit_count=len(unique_result_ids),
        readout_channel=readout_channel,
    )
    reported = ExactClassicalDistribution(
        result_ids,
        _project_unique_probabilities(reported_unique_probabilities, leaf_indexes),
    )
    return physical, reported


def _density_joint_probabilities(
    simulation: DensityMatrixResult,
    slots: tuple[int, ...],
) -> tuple[float, ...]:
    probabilities = [0.0] * (1 << len(slots))
    for basis_index, value in enumerate(simulation.probabilities):
        outcome = 0
        for outcome_bit, slot in enumerate(slots):
            if basis_index & (1 << slot):
                outcome |= 1 << outcome_bit
        probabilities[outcome] += value
    return tuple(probabilities)


def _project_unique_probabilities(
    unique_probabilities: tuple[float, ...],
    leaf_indexes: tuple[int, ...],
) -> tuple[float, ...]:
    probabilities = [0.0] * (1 << len(leaf_indexes))
    for unique_outcome, probability in enumerate(unique_probabilities):
        leaf_outcome = 0
        for leaf_bit, unique_bit in enumerate(leaf_indexes):
            if unique_outcome & (1 << unique_bit):
                leaf_outcome |= 1 << leaf_bit
        probabilities[leaf_outcome] += probability
    return tuple(probabilities)


def _apply_binary_readout(
    probabilities: tuple[float, ...],
    *,
    bit_count: int,
    readout_channel: BinaryReadoutChannel,
) -> tuple[float, ...]:
    reported = [0.0] * len(probabilities)
    for actual_outcome, actual_probability in enumerate(probabilities):
        for reported_outcome in range(len(probabilities)):
            conditional_probability = 1.0
            for bit_index in range(bit_count):
                actual_bit = (actual_outcome >> bit_index) & 1
                reported_bit = (reported_outcome >> bit_index) & 1
                conditional_probability *= readout_channel.probability(
                    reported_bit,
                    actual_bit,
                )
            reported[reported_outcome] += actual_probability * conditional_probability
    return tuple(reported)


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
