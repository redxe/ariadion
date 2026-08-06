from ariadion_language import (
    Angle,
    AngleUnit,
    Program,
    ProgramId,
    SourceNodeId,
    SourceRange,
    deg,
    rad,
    turns,
)
from ariadion_runtime import (
    ExecutionTrace,
    INSPECTION_SCHEMA_VERSION,
    MeasurementBitOrder,
    RunResult,
    StateSnapshot,
    TraceDebuggerError,
    TraceDebuggerSession,
    TRACE_DEBUGGER_SCHEMA_VERSION,
    TraceInspection,
    TraceCaptureOptions,
    TraceStepViewModel,
    inspect_execution_trace,
    run_program,
)

__version__ = "0.1.0"


def run(
    program: Program,
    *,
    trace: TraceCaptureOptions | None = None,
) -> RunResult:
    return run_program(program, trace=trace)


__all__ = [
    "Angle",
    "AngleUnit",
    "ExecutionTrace",
    "INSPECTION_SCHEMA_VERSION",
    "MeasurementBitOrder",
    "Program",
    "ProgramId",
    "RunResult",
    "SourceNodeId",
    "SourceRange",
    "StateSnapshot",
    "TraceDebuggerError",
    "TraceDebuggerSession",
    "TRACE_DEBUGGER_SCHEMA_VERSION",
    "TraceInspection",
    "TraceCaptureOptions",
    "TraceStepViewModel",
    "inspect_execution_trace",
    "deg",
    "rad",
    "run",
    "turns",
]
