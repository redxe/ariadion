from ariadion_language import Program, ProgramId, SourceNodeId, SourceRange
from ariadion_runtime import (
    ExecutionTrace,
    RunResult,
    StateSnapshot,
    TraceCaptureOptions,
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
    "Program",
    "ProgramId",
    "RunResult",
    "SourceNodeId",
    "SourceRange",
    "StateSnapshot",
    "TraceCaptureOptions",
    "run",
]
