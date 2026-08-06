from __future__ import annotations

import math
import unittest
from pathlib import Path

from ariadion import Program, SourceRange, run
from ariadion_ir import OpCode, Operation, OperationProvenance
from daidalon import CompileError, compile_program


class VerticalSliceTests(unittest.TestCase):
    def test_bell_state(self) -> None:
        result = run(Program(2, name="bell").h(0).cx(0, 1))

        self.assertAlmostEqual(result.simulation.probabilities[0], 0.5)
        self.assertAlmostEqual(result.simulation.probabilities[3], 0.5)
        self.assertEqual(result.inspection.entangled_qubits, (0, 1))
        self.assertIn("q0:", result.circuit)
        self.assertIn("entanglement hint", result.report)

    def test_phase_is_visible(self) -> None:
        result = run(Program(1, name="phase").h(0).z(0))
        states = result.inspection.states

        self.assertEqual(len(states), 2)
        self.assertAlmostEqual(states[0].phase_radians, 0.0)
        self.assertAlmostEqual(abs(states[1].phase_radians), math.pi)

    def test_compiler_collects_diagnostics(self) -> None:
        program = Program(2).cx(0, 0).x(4)
        with self.assertRaises(CompileError) as captured:
            compile_program(program)

        codes = {diagnostic.code for diagnostic in captured.exception.diagnostics}
        self.assertEqual(codes, {"A102", "A103"})

    def test_source_identity_survives_lowering(self) -> None:
        source_range = SourceRange(
            file="examples/bell.py",
            line=4,
            column=1,
            end_line=4,
            end_column=13,
        )
        program = Program(2, name="bell", source_id="examples/bell.py")
        program.h(0, source_range=source_range)

        source_operation = program.operations[0]
        result = run(program)
        lowered_operation = result.ir.operations[0]

        self.assertEqual(source_operation.id, "examples/bell.py:operation:0")
        self.assertEqual(lowered_operation.source_id, source_operation.id)
        self.assertEqual(lowered_operation.source_range, source_range)
        self.assertEqual(
            lowered_operation.source.to_json() if lowered_operation.source is not None else None,
            (
                '{"column":1,"end_column":13,"end_line":4,'
                '"file":"examples/bell.py","line":4,'
                '"source_id":"examples/bell.py:operation:0"}'
            ),
        )

    def test_diagnostic_links_to_its_source_operation(self) -> None:
        source_range = SourceRange(
            file="examples/invalid.py",
            line=8,
            column=1,
            end_line=8,
            end_column=11,
        )
        program = Program(2, source_id="examples/invalid.py")
        program.cx(0, 0, source_range=source_range)

        with self.assertRaises(CompileError) as captured:
            compile_program(program)

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "A103")
        self.assertEqual(diagnostic.operation_index, 0)
        self.assertEqual(diagnostic.source_id, "examples/invalid.py:operation:0")
        self.assertEqual(diagnostic.source_range, source_range)
        self.assertEqual(diagnostic.to_dict()["severity"], "error")

    def test_program_captures_available_python_source_location(self) -> None:
        program = Program(1)
        program.h(0)

        source_range = program.operations[0].source_range
        self.assertIsNotNone(source_range)
        assert source_range is not None
        self.assertEqual(Path(source_range.file or "").name, Path(__file__).name)
        self.assertIsNotNone(source_range.line)
        self.assertIsNone(source_range.column)

    def test_global_diagnostic_remains_useful_without_source_location(self) -> None:
        with self.assertRaises(CompileError) as captured:
            compile_program(Program(0))

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "A100")
        self.assertIsNone(diagnostic.source_id)
        self.assertIsNone(diagnostic.source_range)
        self.assertIn("at least one qubit", str(captured.exception))

    def test_generated_operation_can_record_provenance(self) -> None:
        provenance = OperationProvenance(
            parent_source_ids=("examples/bell.py:operation:0",),
            transformation="basis-lowering",
        )
        operation = Operation(OpCode.H, (0,), provenance=provenance)

        self.assertEqual(operation.provenance, provenance)
        self.assertEqual(
            provenance.to_json(),
            (
                '{"parent_source_ids":["examples/bell.py:operation:0"],'
                '"transformation":"basis-lowering"}'
            ),
        )


if __name__ == "__main__":
    unittest.main()
