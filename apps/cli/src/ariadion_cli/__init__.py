from __future__ import annotations

import argparse
import runpy
from collections.abc import Callable, Sequence
from pathlib import Path

from ariadion import (
    Program,
    TraceCaptureOptions,
    TraceDebuggerSession,
    inspect_execution_trace,
    run,
)

from .trace_view import render_trace_step


InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]

_ASCII_OUTPUT_FALLBACK = str.maketrans(
    {
        "═": "=",
        "─": "-",
        "│": "|",
        "●": "o",
    }
)


class CliError(ValueError):
    """Raised for actionable command-line input errors."""


def _emit_output(output: OutputFunction, text: str) -> None:
    try:
        output(text)
    except UnicodeEncodeError:
        output(text.translate(_ASCII_OUTPUT_FALLBACK))


def build_demo(name: str) -> Program:
    if name != "bell":
        raise ValueError(f"unknown demo: {name}")
    return Program(2, name="bell").h(0).cx(0, 1)


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: InputFunction = input,
    output: OutputFunction = print,
) -> int:
    parser = argparse.ArgumentParser(prog="ariadion", description="Ariadion quantum tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="run a bundled demonstration")
    demo.add_argument("name", choices=["bell"])

    run_command = subparsers.add_parser("run", help="run a Python program file")
    run_command.add_argument("path", type=Path, help="Python file defining a top-level program")
    run_command.add_argument(
        "--trace",
        action="store_true",
        help="render every inspected operation step",
    )
    run_command.add_argument(
        "--step",
        type=int,
        metavar="N",
        help="render one one-based inspected operation step",
    )

    debug = subparsers.add_parser("debug", help="navigate an inspected execution trace")
    debug.add_argument("path", type=Path, help="Python file defining a top-level program")

    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = run(build_demo(args.name))
            _emit_output(output, result.circuit)
            _emit_output(output, "")
            _emit_output(output, result.report)
            return 0
        if args.command == "run":
            return _run_file(
                args.path,
                trace_requested=args.trace or args.step is not None,
                step_number=args.step,
                output=output,
            )
        if args.command == "debug":
            return _debug_file(args.path, input_fn=input_fn, output=output)
    except CliError as error:
        _emit_output(output, f"error: {error}")
        return 2
    return 1


def load_program(path: Path) -> Program:
    """Load a Python source file that exposes a top-level `program` builder."""

    resolved_path = path.expanduser().resolve()
    if resolved_path.suffix != ".py":
        raise CliError("program files must use the .py extension")
    if not resolved_path.is_file():
        raise CliError(f"program file not found: {path}")
    try:
        namespace = runpy.run_path(
            str(resolved_path),
            run_name="__ariadion_cli_program__",
        )
    except Exception as error:
        raise CliError(f"could not load {path}: {error}") from error

    program = namespace.get("program")
    if not isinstance(program, Program):
        raise CliError(f"{path} must define a top-level Program named 'program'")
    return program


def run_debugger(
    session: TraceDebuggerSession,
    *,
    input_fn: InputFunction = input,
    output: OutputFunction = print,
) -> None:
    """Navigate an immutable debugger session using n, p, g, and q commands."""

    if not session.has_steps:
        _emit_output(output, "Trace contains no operation steps.")
        return

    _emit_output(output, render_trace_step(session.current_view))
    _emit_output(output, "Commands: n next, p previous, g N go to one-based step N, q quit")
    while True:
        try:
            command = input_fn("debug> ").strip()
        except EOFError:
            _emit_output(output, "Debugger input ended.")
            return
        if command == "q":
            return
        if command == "n":
            if session.current_step_index == session.step_count - 1:
                _emit_output(output, "Already at the final step.")
            else:
                session = session.next()
                _emit_output(output, render_trace_step(session.current_view))
            continue
        if command == "p":
            if session.current_step_index == 0:
                _emit_output(output, "Already at the first step.")
            else:
                session = session.previous()
                _emit_output(output, render_trace_step(session.current_view))
            continue
        if command.startswith("g "):
            session = _go_to_debug_step(session, command[2:].strip(), output=output)
            continue
        _emit_output(output, "Unknown command. Use n, p, g N, or q.")


def _run_file(
    path: Path,
    *,
    trace_requested: bool,
    step_number: int | None,
    output: OutputFunction,
) -> int:
    program = load_program(path)
    if not trace_requested:
        result = run(program)
        _emit_output(output, result.circuit)
        _emit_output(output, "")
        _emit_output(output, result.report)
        return 0

    session = _build_debugger_session(program)
    if step_number is not None:
        view = _view_for_display_step(session, step_number)
        _emit_output(output, render_trace_step(view))
        return 0
    if not session.has_steps:
        _emit_output(output, "Trace contains no operation steps.")
        return 0
    for step_index in range(session.step_count):
        if step_index:
            _emit_output(output, "")
        _emit_output(output, render_trace_step(session.view_at(step_index)))
    return 0


def _debug_file(
    path: Path,
    *,
    input_fn: InputFunction,
    output: OutputFunction,
) -> int:
    session = _build_debugger_session(load_program(path))
    run_debugger(session, input_fn=input_fn, output=output)
    return 0


def _build_debugger_session(program: Program) -> TraceDebuggerSession:
    result = run(program, trace=TraceCaptureOptions(enabled=True))
    if result.trace is None:  # pragma: no cover - runtime contract guard
        raise CliError("trace-enabled execution did not return an execution trace")
    inspection = inspect_execution_trace(result.trace)
    return TraceDebuggerSession(result.ir, result.trace, inspection)


def _view_for_display_step(
    session: TraceDebuggerSession,
    step_number: int,
):
    if step_number < 1:
        raise CliError("--step must be a one-based positive step number")
    if not session.has_steps:
        raise CliError("trace contains no operation steps")
    try:
        return session.view_at(step_number - 1)
    except ValueError as error:
        raise CliError(
            f"--step must be between 1 and {session.step_count} for this trace"
        ) from error


def _go_to_debug_step(
    session: TraceDebuggerSession,
    argument: str,
    *,
    output: OutputFunction,
) -> TraceDebuggerSession:
    try:
        step_number = int(argument)
        view = _view_for_display_step(session, step_number)
    except (ValueError, CliError):
        _emit_output(output, f"Enter a step number between 1 and {session.step_count}.")
        return session
    session = session.go_to(view.step_index)
    _emit_output(output, render_trace_step(session.current_view))
    return session
