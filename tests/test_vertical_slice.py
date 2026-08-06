from __future__ import annotations

import math
import unittest
from pathlib import Path

from ariadion import Program, ProgramId, SourceNodeId, SourceRange, run
from ariadion_core import SnapshotOperationId, SourceRef
from ariadion_ir import OpCode, Operation, OperationProvenance
from daidalon import CompileError, compile_program, make_ir_operation_id


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
        program = Program(2, name="bell", program_id=ProgramId("examples/bell.py"))
        program.h(0, source_range=source_range)

        source_operation = program.operations[0]
        result = run(program)
        lowered_operation = result.ir.operations[0]

        self.assertEqual(source_operation.id, "examples/bell.py:operation:0")
        self.assertEqual(result.ir.id, program.id)
        self.assertEqual(lowered_operation.source_id, source_operation.id)
        self.assertEqual(
            lowered_operation.id,
            "examples/bell.py:operation:0:daidalon:source-lowering:0",
        )
        self.assertEqual(lowered_operation.source_range, source_range)
        self.assertEqual(
            lowered_operation.source.to_json() if lowered_operation.source is not None else None,
            (
                '{"column":1,"end_column":13,"end_line":4,'
                '"file":"examples/bell.py","line":4,'
                '"program_id":"examples/bell.py",'
                '"snapshot_operation_id":"examples/bell.py:operation:0",'
                '"source_node_id":null}'
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
        program = Program(2, program_id=ProgramId("examples/invalid.py"))
        program.cx(0, 0, source_range=source_range)

        with self.assertRaises(CompileError) as captured:
            compile_program(program)

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "A103")
        self.assertEqual(diagnostic.operation_index, 0)
        self.assertEqual(diagnostic.source_id, "examples/invalid.py:operation:0")
        self.assertEqual(diagnostic.program_id, "examples/invalid.py")
        self.assertEqual(
            diagnostic.snapshot_operation_id,
            "examples/invalid.py:operation:0",
        )
        self.assertIsNone(diagnostic.source_node_id)
        self.assertEqual(diagnostic.source_range, source_range)
        self.assertEqual(diagnostic.to_dict()["severity"], "error")

    def test_default_programs_have_distinct_snapshot_scopes(self) -> None:
        first = compile_program(Program(1).h(0))
        second = compile_program(Program(1).x(0))

        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(
            first.operations[0].snapshot_operation_id,
            second.operations[0].snapshot_operation_id,
        )
        self.assertNotEqual(first.operations[0].id, second.operations[0].id)

    def test_durable_node_identity_is_distinct_from_snapshot_identity(self) -> None:
        program = Program(1, program_id=ProgramId("documents/bell"))
        program.h(0, source_node_id=SourceNodeId("node:bell:h"))

        source = compile_program(program).operations[0].source

        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(source.program_id, "documents/bell")
        self.assertEqual(source.snapshot_operation_id, "documents/bell:operation:0")
        self.assertEqual(source.source_node_id, "node:bell:h")
        self.assertEqual(source.source_id, "node:bell:h")

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

    def test_rejected_empty_ids_do_not_mutate_program_or_source_refs(self) -> None:
        program = Program(1)

        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "source node ID must be a non-empty string"):
                program.h(0, source_node_id=SourceNodeId(""))

        with self.assertRaisesRegex(ValueError, "snapshot operation ID must be a non-empty string"):
            SourceRef(
                program_id=ProgramId("documents/bell"),
                snapshot_operation_id=SnapshotOperationId(""),
            )

        self.assertEqual(program.operations, ())

    def test_generated_operations_have_distinct_ir_ids_and_provenance(self) -> None:
        source = SourceRef(
            program_id=ProgramId("documents/bell"),
            snapshot_operation_id=SnapshotOperationId("documents/bell:operation:4"),
            source_node_id=SourceNodeId("node:bell:measure-x"),
        )
        basis_change_id = make_ir_operation_id(source, "basis-lowering", 0)
        measurement_id = make_ir_operation_id(source, "basis-lowering", 1)
        provenance = OperationProvenance(
            parent_source_ids=(source.snapshot_operation_id,),
            transformation="basis-lowering",
        )
        operation = Operation(
            OpCode.H,
            (0,),
            id=basis_change_id,
            source=source,
            provenance=provenance,
        )

        self.assertEqual(operation.provenance, provenance)
        self.assertNotEqual(basis_change_id, measurement_id)
        self.assertEqual(
            basis_change_id,
            "documents/bell:operation:4:daidalon:basis-lowering:0",
        )
        self.assertEqual(
            measurement_id,
            "documents/bell:operation:4:daidalon:basis-lowering:1",
        )
        self.assertEqual(
            provenance.to_json(),
            (
                '{"parent_source_ids":["documents/bell:operation:4"],'
                '"transformation":"basis-lowering"}'
            ),
        )


if __name__ == "__main__":
    unittest.main()
