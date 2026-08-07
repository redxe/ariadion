from __future__ import annotations

import json
import unittest

from ariadion_core import (
    ClassicalBitId,
    LogicalOperationId,
    LogicalQubitId,
    ProgramId,
    SourceOperationId,
    SourceRef,
)
from ariadion_ir import OpCode
from ariadion_language import Basis
from ariadion_runtime import (
    ObservationExecutionKind,
    TraceCaptureOptions,
    inspect_execution_trace,
    run_logical_program,
)
from ariadion_simulator import ExactTerminalObservationError
from ariadion_semantics import (
    ClassicalBitValue,
    LogicalGateOpCode,
    LogicalGateOperation,
    LogicalProgram,
    LogicalQubitValue,
    Observation,
    ObservationReason,
    ReturnValueKind,
    ReturnValueRef,
    ScalarReturn,
    TupleReturn,
)
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

        self.assertEqual(
            first.logical_allocation.policy_name,
            LOGICAL_ALLOCATION_POLICY_NAME,
        )
        self.assertIs(first.allocation, first.logical_allocation)
        self.assertEqual(
            first.logical_allocation.to_dict(),
            {
                "policy_name": "dense-no-reuse-v1",
                "entries": [
                    {
                        "logical_qubit_id": "logical:bell:left",
                        "display_name": "left",
                        "slot": 0,
                    },
                    {
                        "logical_qubit_id": "logical:bell:right",
                        "display_name": "right",
                        "slot": 1,
                    },
                ],
                "peak_live_qubits": 2,
                "allocated_qubit_count": 2,
            },
        )
        self.assertEqual(first.ir.qubit_count, 2)
        self.assertEqual(
            first.readout.to_dict(),
            {
                "observations": [
                    {
                        "result_id": "classical:bell:left",
                        "result_display_name": "left_result",
                        "logical_qubit_id": "logical:bell:left",
                        "allocated_slot": 0,
                        "basis": {"name": "z"},
                        "reason": "program_output",
                        "logical_operation_id": "logical-op:bell:observe-left",
                    },
                    {
                        "result_id": "classical:bell:right",
                        "result_display_name": "right_result",
                        "logical_qubit_id": "logical:bell:right",
                        "allocated_slot": 1,
                        "basis": {"name": "z"},
                        "reason": "program_output",
                        "logical_operation_id": "logical-op:bell:observe-right",
                    },
                ],
                "return_shape": {
                    "kind": "tuple",
                    "items": [
                        {
                            "kind": "scalar",
                            "value": {
                                "kind": "classical_bit",
                                "value_id": "classical:bell:left",
                            },
                        },
                        {
                            "kind": "scalar",
                            "value": {
                                "kind": "classical_bit",
                                "value_id": "classical:bell:right",
                            },
                        },
                    ],
                },
            },
        )
        self.assertEqual(
            [
                (operation.opcode, operation.targets, operation.controls, operation.key)
                for operation in first.ir.operations
            ],
            [
                (OpCode.H, (0,), (), None),
                (OpCode.CX, (1,), (0,), None),
                (OpCode.MEASURE, (0,), (), "classical:bell:left"),
                (OpCode.MEASURE, (1,), (), "classical:bell:right"),
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
        self.assertEqual(
            first.ir.operations[2].observation.to_dict()
            if first.ir.operations[2].observation is not None
            else None,
            {
                "logical_qubit_id": "logical:bell:left",
                "result_id": "classical:bell:left",
                "basis_name": "z",
                "reason": "program_output",
            },
        )

    def test_bell_compilation_runs_through_trace_and_inspection(self) -> None:
        execution = run_logical_program(
            _bell_program(),
            trace=TraceCaptureOptions(enabled=True),
        )

        self.assertIsNotNone(execution.trace)
        assert execution.trace is not None
        trace = execution.trace
        inspection = inspect_execution_trace(trace)

        self.assertAlmostEqual(execution.simulation.probabilities[0], 0.5)
        self.assertAlmostEqual(execution.simulation.probabilities[3], 0.5)
        self.assertEqual(
            execution.classical_output_distribution.result_ids,
            (
                ClassicalBitId("classical:bell:left"),
                ClassicalBitId("classical:bell:right"),
            ),
        )
        for observed, expected in zip(
            execution.classical_output_distribution.probabilities,
            (0.5, 0.0, 0.0, 0.5),
        ):
            self.assertAlmostEqual(observed, expected)
        self.assertEqual(len(execution.classical_output_distribution.probabilities), 4)
        self.assertEqual(
            execution.pre_observation_state.amplitudes,
            execution.simulation.amplitudes,
        )
        self.assertEqual(execution.pre_observation_inspection.entangled_qubits, (0, 1))
        self.assertEqual(len(trace.steps), 4)
        self.assertEqual(
            tuple(step.ir_operation_id for step in trace.steps),
            tuple(operation.id for operation in execution.compilation.ir.operations),
        )
        self.assertEqual(
            trace.steps[2].provenance.parent_logical_operation_ids,
            (LogicalOperationId("logical-op:bell:observe-left"),),
        )
        self.assertAlmostEqual(trace.steps[2].measurement.probabilities[0], 0.5)
        self.assertAlmostEqual(trace.steps[2].measurement.probabilities[1], 0.5)
        self.assertAlmostEqual(trace.steps[3].measurement.probabilities[0], 0.5)
        self.assertAlmostEqual(trace.steps[3].measurement.probabilities[1], 0.5)
        self.assertEqual(len(trace.steps[2].measurement.probabilities), 2)
        self.assertNotEqual(
            execution.classical_output_distribution.probabilities,
            trace.steps[2].measurement.probabilities,
        )
        self.assertEqual(
            trace.steps[2].measurement.execution_kind,
            ObservationExecutionKind.EXACT_TERMINAL_DISTRIBUTION,
        )
        self.assertEqual(inspection.retained_analytic_state.entangled_qubits, (0, 1))
        self.assertEqual(
            inspection.steps[1].provenance.parent_logical_operation_ids,
            (LogicalOperationId("logical-op:bell:cx"),),
        )

    def test_discarded_observation_remains_lowered_but_not_a_public_output(self) -> None:
        bell = _bell_program()
        program = LogicalProgram(
            bell.id,
            bell.name,
            bell.qubits,
            bell.instructions,
            bell.classical_bits,
            ScalarReturn(
                ReturnValueRef(
                    ReturnValueKind.CLASSICAL_BIT,
                    ClassicalBitId("classical:bell:left"),
                )
            ),
        )

        execution = run_logical_program(
            program,
            trace=TraceCaptureOptions(enabled=True),
        )

        self.assertEqual(
            execution.classical_output_distribution.result_ids,
            (ClassicalBitId("classical:bell:left"),),
        )
        self.assertAlmostEqual(execution.classical_output_distribution.probabilities[0], 0.5)
        self.assertAlmostEqual(execution.classical_output_distribution.probabilities[1], 0.5)
        self.assertEqual(len(execution.compilation.readout.observations), 2)
        self.assertIsNotNone(execution.trace)
        assert execution.trace is not None
        self.assertEqual(execution.trace.steps[-1].operation.key, "classical:bell:right")

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
            ClassicalBitId("classical:basis-result"),
            Basis("x"),
            ObservationReason.EXPLICIT,
        )
        program = LogicalProgram(
            ProgramId("logical:unsupported-basis"),
            "unsupported-basis",
            (qubit,),
            (observation,),
            (ClassicalBitValue(observation.result_id),),
        )

        with self.assertRaises(CompileError) as captured:
            compile_logical_program(program)

        diagnostic = captured.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "A201")
        self.assertEqual(diagnostic.logical_operation_id, observation.id)
        self.assertIsNone(diagnostic.source)
        self.assertIn("only z-basis observations", diagnostic.message)

    def test_gate_after_observation_has_terminal_observation_diagnostic(self) -> None:
        qubit = LogicalQubitValue(LogicalQubitId("logical:terminal-qubit"))
        result = ClassicalBitValue(ClassicalBitId("classical:terminal-result"))
        observation = Observation(
            LogicalOperationId("logical-op:terminal:observe"),
            qubit.id,
            result.id,
            Basis("z"),
            ObservationReason.EXPLICIT,
        )
        late_gate = LogicalGateOperation(
            LogicalOperationId("logical-op:terminal:late-h"),
            LogicalGateOpCode.H,
            (qubit.id,),
        )
        program = LogicalProgram(
            ProgramId("logical:non-terminal-observation"),
            "non-terminal-observation",
            (qubit,),
            (observation, late_gate),
            (result,),
        )

        compilation = compile_logical_program(program)
        self.assertEqual(
            tuple(operation.opcode for operation in compilation.ir.operations),
            (OpCode.MEASURE, OpCode.H),
        )
        with self.assertRaises(ExactTerminalObservationError) as captured:
            run_logical_program(program)

        self.assertEqual(captured.exception.code, "A202")


def _bell_program() -> LogicalProgram:
    program_id = ProgramId("logical:bell")
    left = LogicalQubitValue(LogicalQubitId("logical:bell:left"), display_name="left")
    right = LogicalQubitValue(LogicalQubitId("logical:bell:right"), display_name="right")
    left_result = ClassicalBitValue(
        ClassicalBitId("classical:bell:left"),
        display_name="left_result",
    )
    right_result = ClassicalBitValue(
        ClassicalBitId("classical:bell:right"),
        display_name="right_result",
    )
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
                left_result.id,
                Basis("z"),
                ObservationReason.PROGRAM_OUTPUT,
            ),
            Observation(
                LogicalOperationId("logical-op:bell:observe-right"),
                right.id,
                right_result.id,
                Basis("z"),
                ObservationReason.PROGRAM_OUTPUT,
            ),
        ),
        (left_result, right_result),
        TupleReturn(
            (
                ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, left_result.id)),
                ScalarReturn(ReturnValueRef(ReturnValueKind.CLASSICAL_BIT, right_result.id)),
            )
        ),
    )


if __name__ == "__main__":
    unittest.main()
