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
    rad,
    rx,
    ry,
    rz,
    turns,
    x,
    z,
)
from ariadion_runtime import (
    ExecutionTrace,
    ExactClassicalDistribution,
    INSPECTION_SCHEMA_VERSION,
    LogicalRunResult,
    MeasurementBitOrder,
    ObservationExecutionKind,
    ProbabilityScope,
    ReturnedQuantumValue,
    RunResult,
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
    LogicalCallOperation,
    LogicalModule,
    LogicalProgram,
    QuantumArgumentBinding,
    UnboundQuantumParameterError,
)

__version__ = "0.1.0"


@overload
def run(
    program: Program,
    *,
    trace: TraceCaptureOptions | None = None,
) -> RunResult:
    ...


@overload
def run(
    program: LogicalProgram | LogicalModule | QuantumFunction,
    *,
    trace: TraceCaptureOptions | None = None,
) -> LogicalRunResult:
    ...


def run(
    program: Program | LogicalProgram | LogicalModule | QuantumFunction,
    *,
    trace: TraceCaptureOptions | None = None,
) -> RunResult | LogicalRunResult:
    """Execute a builder, logical program, resolved module, or captured function."""

    if isinstance(program, Program):
        return run_program(program, trace=trace)
    if isinstance(program, LogicalProgram):
        return run_logical_program(program, trace=trace)
    if isinstance(program, LogicalModule):
        return run_logical_module(program, trace=trace)
    if isinstance(program, QuantumFunction):
        return run_logical_module(program.to_logical_module(), trace=trace)
    raise TypeError(
        "ariadion.run expects Program, LogicalProgram, LogicalModule, or QuantumFunction"
    )


__all__ = [
    "Angle",
    "AngleUnit",
    "Basis",
    "BasisNamespace",
    "Bit",
    "ExplicitSourceProvider",
    "ExecutionTrace",
    "ExactClassicalDistribution",
    "FrontendDiagnostic",
    "FrontendDiagnosticSeverity",
    "INSPECTION_SCHEMA_VERSION",
    "InspectSourceProvider",
    "MeasurementBitOrder",
    "LogicalRunResult",
    "LogicalCallOperation",
    "LogicalModule",
    "LogicalProgram",
    "ObservationExecutionKind",
    "ProbabilityScope",
    "Program",
    "ProgramId",
    "PythonFrontendError",
    "PythonFunctionSource",
    "PythonSourceProvider",
    "Qubit",
    "QuantumArgumentBinding",
    "QuantumFunction",
    "QuantumFunctionConfig",
    "RunResult",
    "RotationAxis",
    "RotationEffect",
    "RotationExplanation",
    "RotationSourceAngle",
    "ReturnedQuantumValue",
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
    "quantum",
    "rad",
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
