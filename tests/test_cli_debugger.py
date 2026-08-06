from __future__ import annotations

import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

from ariadion_cli import main


class CliDebuggerTests(unittest.TestCase):
    def _program_file(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary_directory = tempfile.TemporaryDirectory[str]()
        path = Path(temporary_directory.name) / "bell_program.py"
        path.write_text(
            "from ariadion import Program\n"
            "\n"
            "program = Program(2, name='bell')\n"
            "program.h(0).cx(0, 1)\n",
            encoding="utf-8",
        )
        return temporary_directory, path

    def test_run_step_renders_the_requested_one_based_trace_step(self) -> None:
        temporary_directory, path = self._program_file()
        self.addCleanup(temporary_directory.cleanup)
        output: list[str] = []

        exit_code = main(
            ["run", str(path), "--step", "2"],
            output=output.append,
        )

        self.assertEqual(exit_code, 0)
        rendered = "\n".join(output)
        self.assertIn("Step 2/2", rendered)
        self.assertIn("Operation: CX controls q0; targets q1", rendered)
        self.assertIn("Source operation ID:", rendered)
        self.assertIn("Circuit (active gate highlighted):", rendered)
        self.assertIn("Newly entangled: q0, q1", rendered)

    def test_run_trace_renders_each_operation_and_debug_navigates(self) -> None:
        temporary_directory, path = self._program_file()
        self.addCleanup(temporary_directory.cleanup)
        trace_output: list[str] = []

        trace_exit_code = main(
            ["run", str(path), "--trace"],
            output=trace_output.append,
        )

        self.assertEqual(trace_exit_code, 0)
        rendered_trace = "\n".join(trace_output)
        self.assertIn("Step 1/2", rendered_trace)
        self.assertIn("Step 2/2", rendered_trace)

        commands: Iterator[str] = iter(("n", "p", "g 2", "q"))
        debug_output: list[str] = []
        debug_exit_code = main(
            ["debug", str(path)],
            input_fn=lambda _: next(commands),
            output=debug_output.append,
        )

        self.assertEqual(debug_exit_code, 0)
        rendered_debug = "\n".join(debug_output)
        self.assertIn(
            "Commands: n next, p previous, g N go to one-based step N, q quit",
            rendered_debug,
        )
        self.assertGreaterEqual(rendered_debug.count("Step 1/2"), 2)
        self.assertGreaterEqual(rendered_debug.count("Step 2/2"), 2)

    def test_run_step_rejects_zero_and_files_without_programs(self) -> None:
        temporary_directory, path = self._program_file()
        self.addCleanup(temporary_directory.cleanup)
        output: list[str] = []

        invalid_step_exit_code = main(
            ["run", str(path), "--step", "0"],
            output=output.append,
        )

        self.assertEqual(invalid_step_exit_code, 2)
        self.assertIn("--step must be a one-based positive step number", output[-1])

        missing_program = Path(temporary_directory.name) / "missing_program.py"
        missing_program.write_text("answer = 42\n", encoding="utf-8")
        missing_program_exit_code = main(
            ["run", str(missing_program)],
            output=output.append,
        )

        self.assertEqual(missing_program_exit_code, 2)
        self.assertIn("must define a top-level Program named 'program'", output[-1])


if __name__ == "__main__":
    unittest.main()
