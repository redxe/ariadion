from __future__ import annotations

import json
import unittest

from ariadion_core import (
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SourceOperationId,
    SourceRef,
)
from ariadion_ir import OpCode
from ariadion_runtime import TraceCaptureOptions, inspect_execution_trace
from ariadion_semantics import (
    Basis,
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalProgram,
    LogicalQubitValue,
    Observation,
    ObservationReason,
)
from ariadion_simulator import SimulationExecution, simulate
from daidalon import (
    LOGICAL_ALLOCATION_POLICY_NAME,
    CompileError,
    compile_logical_program,
)


class LogicalCompilationTests(unittest.TestCase):
    def test_bell_program_lowers_through_deterministic_dense_allocation(self) -> None:
        program = _bell_program()

        first = compile_logical_program(program)
        second = compile_logical_program(program)

        self.assertEqual(first.allocation.policy_name, LOGICAL_ALLOCATION_POLICY_NAME)
        self.assertEqual(
            first.allocation.to_dict(),
            {
                "policy_name": "dense-no-reuse-v1",
                "entries": [
                    {"logical_qubit_id": "logical:bell:left", "slot": 0},
                    {"logical_qubit_id": "logical:bell:right", "slot": 1},
                ],
                "peak_live_qubits": 2,
                "allocated_qubit_count": 2,
            },
        )
        self.assertEqual(first.ir.qubit_count, 2)
        self.assertEqual(
            [
                (operation.opcode, operation.targets, operation.controls)
                for operation in first.ir.operations
            ],
            [
                (OpCode.H, (0,), ()),
                (OpCode.CX, (1,), (0,)),
                (OpCode.MEASURE, (0,), ()),
                (OpCode.MEASURE, (1,), ()),
            ],
        )
        self.assertEqual(
            [operation.id for operation in first.ir.operations],
            [
                "logical-op:bell:h:daidalon:logical-allocation-lowering:0",
                "logical-op:bell:cx:daidalon:logical-allocation-lowering:0",
                "logical-op:bell:observe-left:daidalon:logical-allocation-lowering:0",
                "logical-op:bell:observe-right:daidalon:logical-allocation-lowering:0",
            ],
        )
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(json.loads(first.to_json()), first.to_dict())
        self.assertEqual(
            first.ir.operations[1].provenance.parent_logical_operation_ids,
            (LogicalOperationId("logical-op:bell:cx"),),
        )

    def test_bell_compilation_runs_through_trace_and_inspection(self) -> None:
        compilation = compile_logical_program(_bell_program())
        execution = simulate(compilation.ir, trace=TraceCaptureOptions(enabled=True))

        self.assertIsInstance(execution, SimulationExecution)
        self.assertIsNotNone(execution.trace)
        assert execution.trace is not None
        trace = execution.trace
        inspection = inspect_execution_trace(trace)

        self.assertAlmostEqual(execution.result.probabilities[0], 0.5)
        self.assertAlmostEqual(execution.result.probabilities[3], 0.5)
        self.assertEqual(len(trace.steps), 4)
        self.assertEqual(
            tuple(step.ir_operation_id for step in trace.steps),
            tuple(operation.id for operation in compilation.ir.operations),
        )
        self.assertEqual(
            trace.steps[2].provenance.parent_logical_operation_ids,
            (LogicalOperationId("logical-op:bell:observe-left"),),
        )
        self.assertAlmostEqual(trace.steps[2].measurement.probabilities[0], 0.5)
        self.assertAlmostEqual(trace.steps[2].measurement.probabilities[1], 0.5)
        self.assertAlmostEqual(trace.steps[3].measurement.probabilities[0], 0.5)
        self.assertAlmostEqual(trace.steps[3].measurement.probabilities[1], 0.5)
        self.assertEqual(inspection.final.entangled_qubits, (0, 1))
        self.assertEqual(
            inspection.steps[1].provenance.parent_logical_operation_ids,
            (LogicalOperationId("logical-op:bell:cx"),),
        )

    def test_semantic_source_identity_is_preserved_without_a_snapshot_identity(self) -> None:
        program_id = ProgramId("logical:source-identity")
        source = SourceRef(
            program_id=program_id,
            source_operation_id=SourceOperationId("source-op:logical:h"),
        )
        qubit = LogicalQubitValue(LogicalQubitId("logical:source-qubit"))
        gate = LogicalGateOperation(
            LogicalOperationId("logical-op:source:h"),
            LogicalGateOpCode.H,
            (qubit.id,),
            source=source,
        )
        program = LogicalProgram(program_id, "source-identity", (qubit,), (gate,))

        operation = compile_logical_program(program).ir.operations[0]

        self.assertEqual(operation.source_operation_id, "source-op:logical:h")
        self.assertIsNone(operation.snapshot_operation_id)
        self.assertEqual(
            operation.provenance.parent_source_ids,
            (SourceOperationId("source-op:logical:h"),),
        )
        self.assertEqual(
            operation.provenance.parent_logical_operation_ids,
            (LogicalOperationId("logical-op:source:h"),),
        )

    def test_non_z_observations_have_a_structured_unsupported_diagnostic(self) -> None:
        qubit = LogicalQubitValue(LogicalQubitId("logical:basis-qubit"))
        observation = Observation(
            LogicalOperationId("logical-op:basis:observe"),
            qubit.id,
            Basis("x"),
            ObservationReason.EXPLICIT,
        )
        program = LogicalProgram(
            ProgramId("logical:unsupported-basis"),
            "unsupported-basis",
            (qubit,),
            (observation,),
        )

        with self.assertRaises(CompileError) as captured:
            compile_logical_program(program)

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "A201")
        self.assertEqual(diagnostic.logical_operation_id, observation.id)
        self.assertIsNone(diagnostic.source)
        self.assertIn("only z-basis observations", diagnostic.message)


def _bell_program() -> LogicalProgram:
    program_id = ProgramId("logical:bell")
    left = LogicalQubitValue(LogicalQubitId("logical:bell:left"), display_name="left")
    right = LogicalQubitValue(LogicalQubitId("logical:bell:right"), display_name="right")
    return LogicalProgram(
        program_id,
        "bell",
        (left, right),
        (
            LogicalGateOperation(
                LogicalOperationId("logical-op:bell:h"),
                LogicalGateOpCode.H,
                (left.id,),
            ),
            LogicalGateOperation(
                LogicalOperationId("logical-op:bell:cx"),
                LogicalGateOpCode.CX,
                (right.id,),
                controls=(left.id,),
            ),
            Observation(
                LogicalOperationId("logical-op:bell:observe-left"),
                left.id,
                Basis("z"),
                ObservationReason.PROGRAM_OUTPUT,
            ),
            Observation(
                LogicalOperationId("logical-op:bell:observe-right"),
                right.id,
                Basis("z"),
                ObservationReason.PROGRAM_OUTPUT,
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
