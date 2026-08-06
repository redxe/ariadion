from ariadion_language import Program, ProgramId, SourceNodeId, SourceRange
from ariadion_runtime import (
    ExecutionTrace,
    INSPECTION_SCHEMA_VERSION,
    RunResult,
    StateSnapshot,
    TraceDebuggerError,
    TraceDebuggerSession,
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
    "ExecutionTrace",
    "INSPECTION_SCHEMA_VERSION",
    "Program",
    "ProgramId",
    "RunResult",
    "SourceNodeId",
    "SourceRange",
    "StateSnapshot",
    "TraceDebuggerError",
    "TraceDebuggerSession",
    "TraceInspection",
    "TraceCaptureOptions",
    "TraceStepViewModel",
    "inspect_execution_trace",
    "run",
]
