from ariadion_language import Program, SourceRange
from ariadion_runtime import RunResult, run_program

__version__ = "0.1.0"


def run(program: Program) -> RunResult:
    return run_program(program)


__all__ = ["Program", "RunResult", "SourceRange", "run"]
