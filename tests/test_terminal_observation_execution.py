from __future__ import annotations

import json
import unittest

from ariadion import Program, ProgramId
from ariadion_core import (
    ClassicalBitId,
    IrOperationId,
    LogicalQubitId,
    SnapshotOperationId,
    SourceOperationId,
    SourceRef,
)
from ariadion_ir import CircuitIR, ObservationMetadata, OpCode, Operation
from ariadion_runtime import (
    EXECUTION_TRACE_SCHEMA_VERSION,
    ExactClassicalDistribution,
    MeasurementBitOrder,
    ObservationExecutionKind,
    ProbabilityScope,
    TraceCaptureOptions,
)
from ariadion_simulator import ExactTerminalObservationError, SimulationExecution, simulate
from daidalon import compile_program


class TerminalObservationExecutionTests(unittest.TestCase):
    def test_exact_engine_rejects_a_gate_after_observation(self) -> None:
        circuit = CircuitIR(
            ProgramId("examples/non-terminal.py"),
            "non-terminal",
            1,
            (
                Operation(OpCode.H, (0,), IrOperationId("non-terminal:h")),
                Operation(OpCode.MEASURE, (0,), IrOperationId("non-terminal:measure")),
                Operation(OpCode.X, (0,), IrOperationId("non-terminal:x")),
            ),
        )

        with self.assertRaises(ExactTerminalObservationError) as captured:
            simulate(circuit)

        error = captured.exception
        self.assertEqual(error.code, "A202")
        self.assertEqual(error.observed_operation_id, "non-terminal:measure")
        self.assertEqual(error.observed_step_index, 1)
        self.assertEqual(error.following_operation_id, "non-terminal:x")
        self.assertEqual(error.following_step_index, 2)
        self.assertIn("terminal observations only", str(error))

    def test_terminal_compatibility_measurement_retains_analytic_state(self) -> None:
        circuit = compile_program(
            Program(1, program_id=ProgramId("examples/terminal-measurement.py"))
            .h(0)
            .measure(0, key="result")
        )

        execution = simulate(circuit, trace=TraceCaptureOptions(enabled=True))

        self.assertIsInstance(execution, SimulationExecution)
        self.assertIsNotNone(execution.trace)
        assert execution.trace is not None
        measurement_step = execution.trace.steps[-1]
        self.assertAlmostEqual(execution.result.probabilities[0], 0.5)
        self.assertAlmostEqual(execution.result.probabilities[1], 0.5)
        self.assertEqual(measurement_step.before, measurement_step.after)
        self.assertEqual(
            execution.trace.retained_analytic_state.amplitudes,
            execution.result.amplitudes,
        )
        self.assertIsNotNone(measurement_step.measurement)
        assert measurement_step.measurement is not None
        self.assertEqual(
            measurement_step.measurement.execution_kind,
            ObservationExecutionKind.EXACT_TERMINAL_DISTRIBUTION,
        )

    def test_exact_distribution_is_joint_ordered_classical_data(self) -> None:
        distribution = ExactClassicalDistribution(
            (ClassicalBitId("classical:left"), ClassicalBitId("classical:right")),
            (0.5, 0.0, 0.0, 0.5),
        )

        self.assertEqual(distribution.bit_order, MeasurementBitOrder.TARGETS_LSB_FIRST)
        self.assertEqual(distribution.scope, ProbabilityScope.JOINT_RETURN)
        self.assertEqual(
            json.loads(distribution.to_json()),
            {
                "result_ids": ["classical:left", "classical:right"],
                "probabilities": [0.5, 0.0, 0.0, 0.5],
                "bit_order": "targets_lsb_first",
                "scope": "joint_return",
            },
        )

    def test_observation_metadata_requires_measurement_and_matching_result_key(self) -> None:
        metadata = ObservationMetadata(
            LogicalQubitId("logical:metadata-qubit"),
            ClassicalBitId("classical:metadata-result"),
            "z",
            "explicit",
        )

        with self.assertRaisesRegex(ValueError, "only MEASURE operations"):
            Operation(
                OpCode.H,
                (0,),
                IrOperationId("metadata:h"),
                observation=metadata,
            )
        with self.assertRaisesRegex(ValueError, "key must match"):
            Operation(
                OpCode.MEASURE,
                (0,),
                IrOperationId("metadata:measure"),
                key="other-result",
                observation=metadata,
            )

        operation = Operation(
            OpCode.MEASURE,
            (0,),
            IrOperationId("metadata:valid"),
            key="classical:metadata-result",
            observation=metadata,
        )
        self.assertEqual(operation.observation, metadata)

    def test_trace_serializes_legacy_and_semantic_source_references_at_schema_three(self) -> None:
        circuit_id = ProgramId("examples/source-forms.py")
        legacy_source = SourceRef(
            program_id=circuit_id,
            snapshot_operation_id=SnapshotOperationId("examples/source-forms.py:operation:0"),
        )
        semantic_source = SourceRef(
            program_id=circuit_id,
            source_operation_id=SourceOperationId("source-operation:semantic:1"),
        )
        circuit = CircuitIR(
            circuit_id,
            "source-forms",
            1,
            (
                Operation(
                    OpCode.H,
                    (0,),
                    IrOperationId("source-forms:h"),
                    source=legacy_source,
                ),
                Operation(
                    OpCode.Z,
                    (0,),
                    IrOperationId("source-forms:z"),
                    source=semantic_source,
                ),
            ),
        )

        execution = simulate(circuit, trace=TraceCaptureOptions(enabled=True))

        self.assertIsNotNone(execution.trace)
        assert execution.trace is not None
        payload = json.loads(execution.trace.to_json())
        self.assertEqual(EXECUTION_TRACE_SCHEMA_VERSION, 3)
        self.assertEqual(payload["schema_version"], 3)
        first_source = payload["steps"][0]["operation"]["source"]
        second_source = payload["steps"][1]["operation"]["source"]
        self.assertEqual(
            first_source["snapshot_operation_id"],
            "examples/source-forms.py:operation:0",
        )
        self.assertIsNone(second_source["snapshot_operation_id"])
        self.assertEqual(second_source["source_operation_id"], "source-operation:semantic:1")


if __name__ == "__main__":
    unittest.main()
