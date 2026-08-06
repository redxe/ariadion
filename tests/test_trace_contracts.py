from __future__ import annotations

import json
import unittest

from ariadion import Program, ProgramId, SourceNodeId
from ariadion_runtime import (
    EXECUTION_TRACE_SCHEMA_VERSION,
    ExecutionMetadata,
    ExecutionMode,
    ExecutionTrace,
    MeasurementEvent,
    MeasurementRecordKind,
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
        )

        exact_step = TraceStep(0, operation, snapshot, snapshot, measurement=exact)
        sampled_step = TraceStep(0, operation, snapshot, snapshot, measurement=sampled)

        self.assertEqual(exact.to_dict()["kind"], "exact_probabilities")
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


if __name__ == "__main__":
    unittest.main()
