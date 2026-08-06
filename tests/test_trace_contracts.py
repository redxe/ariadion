from __future__ import annotations

import json
import math
import unittest

from ariadion import Program, ProgramId, SourceNodeId
from ariadion_core import IrOperationId, canonical_json
from ariadion_ir import OpCode, Operation
from ariadion_runtime import (
    EXECUTION_TRACE_SCHEMA_VERSION,
    ExecutionMetadata,
    ExecutionMode,
    ExecutionTrace,
    MeasurementEvent,
    MeasurementBitOrder,
    MeasurementRecordKind,
    ObservationExecutionKind,
    ResourceMetric,
    StateSnapshot,
    TraceCaptureOptions,
    TraceStep,
)
from ariadion_simulator import simulate
from daidalon import compile_program


class TraceContractTests(unittest.TestCase):
    def test_empty_circuit_trace_retains_only_the_initial_snapshot(self) -> None:
        circuit = compile_program(Program(1, program_id=ProgramId("examples/empty.py")))
        initial = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))

        trace = ExecutionTrace(circuit.id, initial)

        self.assertEqual(trace.steps, ())
        self.assertEqual(trace.final_state, initial)
        self.assertEqual(trace.to_dict()["schema_version"], EXECUTION_TRACE_SCHEMA_VERSION)
        self.assertEqual(trace.to_dict()["circuit_id"], circuit.id)

    def test_one_operation_trace_maps_state_and_source_identity(self) -> None:
        program = Program(1, program_id=ProgramId("examples/phase.py"))
        program.h(0, source_node_id=SourceNodeId("node:phase:h"))
        circuit = compile_program(program)
        initial = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))
        simulated = simulate(circuit)
        after = StateSnapshot(circuit.id, circuit.qubit_count, simulated.amplitudes)
        step = TraceStep(0, circuit.operations[0], initial, after)

        trace = ExecutionTrace(circuit.id, initial, (step,))

        self.assertEqual(step.ir_operation_id, circuit.operations[0].id)
        self.assertEqual(step.source, circuit.operations[0].source)
        self.assertEqual(step.source_node_id, "node:phase:h")
        self.assertEqual(trace.final_state.amplitudes, simulated.amplitudes)
        self.assertEqual(trace.final_state, after)

    def test_snapshots_reject_mutable_amplitudes_and_preserve_tuples(self) -> None:
        circuit = compile_program(Program(1, program_id=ProgramId("examples/immutable.py")))

        with self.assertRaisesRegex(ValueError, "snapshot amplitudes must be a tuple"):
            StateSnapshot(circuit.id, circuit.qubit_count, [1 + 0j, 0j])  # type: ignore[arg-type]

        snapshot = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))
        self.assertIsInstance(snapshot.amplitudes, tuple)
        with self.assertRaises(AttributeError):
            snapshot.amplitudes = (0j, 1 + 0j)  # type: ignore[misc]

    def test_snapshots_reject_non_finite_amplitudes(self) -> None:
        circuit = compile_program(Program(1, program_id=ProgramId("examples/non-finite.py")))

        for amplitude in (complex(math.nan, 0), complex(0, math.inf)):
            with self.subTest(amplitude=amplitude):
                with self.assertRaisesRegex(ValueError, "snapshot amplitudes must be finite"):
                    StateSnapshot(circuit.id, circuit.qubit_count, (amplitude, 0j))

    def test_canonical_json_rejects_non_finite_values(self) -> None:
        with self.assertRaises(ValueError):
            canonical_json({"value": math.nan})

    def test_trace_steps_must_be_contiguous_and_state_linked(self) -> None:
        program = Program(1, program_id=ProgramId("examples/linked.py"))
        program.h(0)
        circuit = compile_program(program)
        initial = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))
        after = StateSnapshot(circuit.id, circuit.qubit_count, simulate(circuit).amplitudes)
        step = TraceStep(1, circuit.operations[0], initial, after)

        with self.assertRaisesRegex(ValueError, "indexes must be contiguous"):
            ExecutionTrace(circuit.id, initial, (step,))

    def test_measurement_records_keep_exact_and_sampled_data_distinct(self) -> None:
        program = Program(1, program_id=ProgramId("examples/measurement.py"))
        program.measure(0, key="result")
        circuit = compile_program(program)
        snapshot = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))
        operation = circuit.operations[0]
        exact = MeasurementEvent(
            operation.id,
            (0,),
            MeasurementRecordKind.EXACT_PROBABILITIES,
            key="result",
            probabilities=(1.0, 0.0),
        )
        sampled = MeasurementEvent(
            operation.id,
            (0,),
            MeasurementRecordKind.SAMPLED_OUTCOME,
            key="result",
            outcome=(0,),
            execution_kind=ObservationExecutionKind.SAMPLED_COLLAPSE,
        )

        exact_step = TraceStep(0, operation, snapshot, snapshot, measurement=exact)
        sampled_step = TraceStep(0, operation, snapshot, snapshot, measurement=sampled)

        self.assertEqual(exact.to_dict()["kind"], "exact_probabilities")
        self.assertEqual(
            exact.to_dict()["bit_order"],
            MeasurementBitOrder.TARGETS_LSB_FIRST.value,
        )
        self.assertEqual(sampled.to_dict()["kind"], "sampled_outcome")
        with self.assertRaisesRegex(ValueError, "exact execution traces"):
            ExecutionTrace(circuit.id, snapshot, (sampled_step,))

        sampled_trace = ExecutionTrace(
            circuit.id,
            snapshot,
            (sampled_step,),
            metadata=ExecutionMetadata(mode=ExecutionMode.SAMPLED, seed=42),
        )
        self.assertEqual(sampled_trace.metadata.seed, 42)
        self.assertEqual(exact_step.measurement, exact)

    def test_measurement_events_must_match_their_operations(self) -> None:
        program = Program(1, program_id=ProgramId("examples/measurement-binding.py"))
        program.h(0)
        program.measure(0, key="result")
        circuit = compile_program(program)
        snapshot = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))
        h_operation, measurement_operation = circuit.operations

        non_measurement_event = MeasurementEvent(
            h_operation.id,
            (0,),
            MeasurementRecordKind.EXACT_PROBABILITIES,
            probabilities=(1.0, 0.0),
        )
        with self.assertRaisesRegex(ValueError, "require a MEASURE operation"):
            TraceStep(0, h_operation, snapshot, snapshot, measurement=non_measurement_event)

        wrong_operation_id = MeasurementEvent(
            IrOperationId("examples/measurement-binding.py:other"),
            (0,),
            MeasurementRecordKind.EXACT_PROBABILITIES,
            key="result",
            probabilities=(1.0, 0.0),
        )
        with self.assertRaisesRegex(ValueError, "operation ID must match"):
            TraceStep(
                1,
                measurement_operation,
                snapshot,
                snapshot,
                measurement=wrong_operation_id,
            )

        wrong_targets = MeasurementEvent(
            measurement_operation.id,
            (1,),
            MeasurementRecordKind.EXACT_PROBABILITIES,
            key="result",
            probabilities=(1.0, 0.0),
        )
        with self.assertRaisesRegex(ValueError, "targets must match"):
            TraceStep(1, measurement_operation, snapshot, snapshot, measurement=wrong_targets)

        wrong_key = MeasurementEvent(
            measurement_operation.id,
            (0,),
            MeasurementRecordKind.EXACT_PROBABILITIES,
            key="other",
            probabilities=(1.0, 0.0),
        )
        with self.assertRaisesRegex(ValueError, "key must match"):
            TraceStep(1, measurement_operation, snapshot, snapshot, measurement=wrong_key)

    def test_exact_measurement_events_validate_probability_distributions(self) -> None:
        operation = Operation(
            OpCode.MEASURE,
            (0,),
            IrOperationId("examples/probabilities.py:measure"),
            key="result",
        )

        with self.assertRaisesRegex(ValueError, "probability count"):
            MeasurementEvent(
                operation.id,
                (0,),
                MeasurementRecordKind.EXACT_PROBABILITIES,
                key="result",
                probabilities=(1.0,),
            )
        with self.assertRaisesRegex(ValueError, "probabilities must sum to one"):
            MeasurementEvent(
                operation.id,
                (0,),
                MeasurementRecordKind.EXACT_PROBABILITIES,
                key="result",
                probabilities=(0.25, 0.25),
            )
        with self.assertRaisesRegex(ValueError, "targets must be unique"):
            MeasurementEvent(
                operation.id,
                (0, 0),
                MeasurementRecordKind.EXACT_PROBABILITIES,
                key="result",
                probabilities=(0.25, 0.25, 0.25, 0.25),
            )

    def test_measurement_targets_must_fit_the_snapshot_width(self) -> None:
        circuit_id = ProgramId("examples/out-of-range.py")
        snapshot = StateSnapshot(circuit_id, 1, (1 + 0j, 0j))
        operation = Operation(
            OpCode.MEASURE,
            (1,),
            IrOperationId("examples/out-of-range.py:measure"),
            key="result",
        )
        event = MeasurementEvent(
            operation.id,
            (1,),
            MeasurementRecordKind.EXACT_PROBABILITIES,
            key="result",
            probabilities=(1.0, 0.0),
        )

        with self.assertRaisesRegex(ValueError, "within the snapshot width"):
            TraceStep(0, operation, snapshot, snapshot, measurement=event)

    def test_traces_reject_duplicate_ir_operation_ids(self) -> None:
        program = Program(1, program_id=ProgramId("examples/duplicate-operation.py"))
        program.h(0)
        circuit = compile_program(program)
        initial = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))
        after = StateSnapshot(circuit.id, circuit.qubit_count, (0j, 1 + 0j))
        operation = circuit.operations[0]
        first = TraceStep(0, operation, initial, after)
        duplicate = TraceStep(1, operation, after, after)

        with self.assertRaisesRegex(ValueError, "IR operation IDs must be unique"):
            ExecutionTrace(circuit.id, initial, (first, duplicate))

    def test_contract_serialization_is_versioned_and_deterministic(self) -> None:
        circuit = compile_program(Program(1, program_id=ProgramId("examples/serial.py")))
        initial = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))
        metadata = ExecutionMetadata(
            duration_ns=12,
            resource_metrics=(ResourceMetric("statevector_bytes", 32, "bytes"),),
        )
        trace = ExecutionTrace(circuit.id, initial, metadata=metadata)

        payload = json.loads(trace.to_json())

        self.assertEqual(payload["schema_version"], EXECUTION_TRACE_SCHEMA_VERSION)
        self.assertEqual(payload["initial_state"]["representation"], "state_vector")
        self.assertEqual(payload["metadata"]["resource_metrics"][0]["name"], "statevector_bytes")
        self.assertEqual(trace.to_json(), trace.to_json())
        self.assertFalse(TraceCaptureOptions().enabled)

    def test_schema_version_one_is_rejected_after_observation_execution_upgrade(self) -> None:
        circuit = compile_program(Program(1, program_id=ProgramId("examples/schema.py")))
        initial = StateSnapshot(circuit.id, circuit.qubit_count, (1 + 0j, 0j))

        with self.assertRaisesRegex(ValueError, "supported trace schema"):
            ExecutionTrace(circuit.id, initial, schema_version=1)


if __name__ == "__main__":
    unittest.main()
