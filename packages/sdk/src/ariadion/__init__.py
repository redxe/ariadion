from typing import overload

from ariadion_frontend_python import (
    ExplicitSourceProvider,
    FrontendDiagnostic,
    FrontendDiagnosticSeverity,
    InspectSourceProvider,
    PythonFrontendError,
    PythonFunctionSource,
    PythonSourceProvider,
    QuantumFunction,
    QuantumFunctionConfig,
    capture_python_function,
    quantum,
)
from ariadion_language import (
    Angle,
    AngleUnit,
    Basis,
    BasisNamespace,
    Bit,
    Program,
    ProgramId,
    SourceNodeId,
    SourceRange,
    Qubit,
    basis,
    cx,
    deg,
    h,
    observe,
    rad,
    reset,
    rx,
    ry,
    rz,
    turns,
    x,
    z,
)
from ariadion_ir import OpCode
from ariadion_runtime import (
    ExecutionTrace,
    ExactClassicalDistribution,
    INSPECTION_SCHEMA_VERSION,
    LogicalRunResult,
    MeasurementBitOrder,
    ObservationExecutionKind,
    ProbabilityScope,
    ResetEvent,
    ReturnedQuantumValue,
    RunResult,
    SampledClassicalResult,
    SampledExecutionRequest,
    SampledLogicalRunResult,
    SampledRunResult,
    SampledShot,
    RotationAxis,
    RotationEffect,
    RotationExplanation,
    RotationSourceAngle,
    StateSnapshot,
    TraceDebuggerError,
    TraceDebuggerSession,
    TRACE_DEBUGGER_SCHEMA_VERSION,
    TraceInspection,
    TraceCaptureOptions,
    TraceStepViewModel,
    inspect_execution_trace,
    run_logical_module,
    run_logical_program,
    run_program,
)
from ariadion_semantics import (
    AmplitudeDampingChannel,
    BinaryReadoutChannel,
    BitFlipChannel,
    DepolarizingChannel,
    EvolutionModel,
    ExecutableNoiseModel,
    GateChannelBinding,
    LogicalCallOperation,
    LogicalModule,
    LogicalProgram,
    NoiseBindingResult,
    NoiseFeature,
    NoiseModelOrigin,
    PhaseDampingChannel,
    PhaseFlipChannel,
    QuantumChannel,
    QuantumArgumentBinding,
    QuantumCallResult,
    ReadoutChannelBinding,
    SimulationRequest,
    UnboundQuantumParameterError,
)

__version__ = "0.1.0"


@overload
def run(
    program: Program,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: None = None,
) -> RunResult:
    ...


@overload
def run(
    program: LogicalProgram | LogicalModule | QuantumFunction,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: None = None,
) -> LogicalRunResult:
    ...


@overload
def run(
    program: Program,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: SampledExecutionRequest,
) -> SampledRunResult:
    ...


@overload
def run(
    program: LogicalProgram | LogicalModule | QuantumFunction,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: SampledExecutionRequest,
) -> SampledLogicalRunResult:
    ...


def run(
    program: Program | LogicalProgram | LogicalModule | QuantumFunction,
    *,
    trace: TraceCaptureOptions | None = None,
    execution: SampledExecutionRequest | None = None,
) -> RunResult | LogicalRunResult | SampledRunResult | SampledLogicalRunResult:
    """Execute a builder, logical program, resolved module, or captured function."""

    if isinstance(program, Program):
        return run_program(program, trace=trace, execution=execution)
    if isinstance(program, LogicalProgram):
        return run_logical_program(program, trace=trace, execution=execution)
    if isinstance(program, LogicalModule):
        return run_logical_module(program, trace=trace, execution=execution)
    if isinstance(program, QuantumFunction):
        return run_logical_module(
            program.to_logical_module(),
            trace=trace,
            execution=execution,
        )
    raise TypeError(
        "ariadion.run expects Program, LogicalProgram, LogicalModule, or QuantumFunction"
    )


__all__ = [
    "AmplitudeDampingChannel",
    "Angle",
    "AngleUnit",
    "Basis",
    "BasisNamespace",
    "BinaryReadoutChannel",
    "Bit",
    "BitFlipChannel",
    "DepolarizingChannel",
    "EvolutionModel",
    "ExecutableNoiseModel",
    "ExplicitSourceProvider",
    "ExecutionTrace",
    "ExactClassicalDistribution",
    "FrontendDiagnostic",
    "FrontendDiagnosticSeverity",
    "INSPECTION_SCHEMA_VERSION",
    "InspectSourceProvider",
    "MeasurementBitOrder",
    "LogicalRunResult",
    "GateChannelBinding",
    "LogicalCallOperation",
    "LogicalModule",
    "LogicalProgram",
    "ObservationExecutionKind",
    "NoiseBindingResult",
    "NoiseFeature",
    "NoiseModelOrigin",
    "OpCode",
    "PhaseDampingChannel",
    "PhaseFlipChannel",
    "ProbabilityScope",
    "Program",
    "ProgramId",
    "PythonFrontendError",
    "PythonFunctionSource",
    "PythonSourceProvider",
    "Qubit",
    "QuantumArgumentBinding",
    "QuantumChannel",
    "QuantumCallResult",
    "QuantumFunction",
    "QuantumFunctionConfig",
    "RunResult",
    "SampledClassicalResult",
    "SampledExecutionRequest",
    "SampledLogicalRunResult",
    "SampledRunResult",
    "SampledShot",
    "SimulationRequest",
    "RotationAxis",
    "RotationEffect",
    "RotationExplanation",
    "RotationSourceAngle",
    "ReturnedQuantumValue",
    "ReadoutChannelBinding",
    "ResetEvent",
    "SourceNodeId",
    "SourceRange",
    "StateSnapshot",
    "TraceDebuggerError",
    "TraceDebuggerSession",
    "TRACE_DEBUGGER_SCHEMA_VERSION",
    "TraceInspection",
    "TraceCaptureOptions",
    "TraceStepViewModel",
    "UnboundQuantumParameterError",
    "basis",
    "capture_python_function",
    "cx",
    "inspect_execution_trace",
    "deg",
    "h",
    "observe",
    "quantum",
    "rad",
    "reset",
    "rx",
    "ry",
    "rz",
    "run",
    "run_logical_module",
    "run_logical_program",
    "turns",
    "x",
    "z",
]
