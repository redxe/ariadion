from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import ariadion_simulator.statevector as statevector
from ariadion import Program, ProgramId, SourceNodeId, run
from ariadion_ir import OpCode
from ariadion_runtime import (
    ExecutionMode,
    ExecutionTrace,
    MeasurementRecordKind,
    TraceCaptureOptions,
)
from ariadion_simulator import (
    EXPECTED_STATE_VECTOR_NORM,
    STATE_VECTOR_NORM_ABS_TOLERANCE,
    SimulationExecution,
    SimulationNormError,
    SimulationResult,
    simulate,
)
from daidalon import compile_program


class TraceSimulationTests(unittest.TestCase):
    def test_bell_trace_captures_contiguous_source_linked_transitions(self) -> None:
        program = Program(2, name="bell", program_id=ProgramId("examples/bell.py"))
        program.h(0, source_node_id=SourceNodeId("node:bell:h"))
        program.cx(0, 1, source_node_id=SourceNodeId("node:bell:cx"))

        result = run(program, trace=TraceCaptureOptions(enabled=True))
        trace = result.trace

        self.assertIsNotNone(trace)
        assert trace is not None
        scale = 1 / math.sqrt(2)
        h_step, cx_step = trace.steps

        self.assertEqual(trace.initial_state.amplitudes, (1 + 0j, 0j, 0j, 0j))
        self.assertEqual(tuple(step.index for step in trace.steps), (0, 1))
        self.assertEqual(h_step.before, trace.initial_state)
        self.assertEqual(cx_step.before, h_step.after)
        self.assertEqual(trace.final_state, cx_step.after)
        self.assertEqual(trace.final_state.amplitudes, result.simulation.amplitudes)
        self.assertEqual(trace.metadata.mode, ExecutionMode.EXACT)

        self.assertAlmostEqual(h_step.after.amplitudes[0].real, scale)
        self.assertAlmostEqual(h_step.after.amplitudes[1].real, scale)
        self.assertEqual(h_step.after.amplitudes[2:], (0j, 0j))
        self.assertAlmostEqual(cx_step.after.amplitudes[0].real, scale)
        self.assertAlmostEqual(cx_step.after.amplitudes[3].real, scale)
        self.assertEqual(cx_step.after.amplitudes[1:3], (0j, 0j))

        self.assertEqual(h_step.ir_operation_id, result.ir.operations[0].id)
        self.assertEqual(cx_step.ir_operation_id, result.ir.operations[1].id)
        self.assertEqual(h_step.source, result.ir.operations[0].source)
        self.assertEqual(cx_step.source, result.ir.operations[1].source)
        self.assertEqual(h_step.source_node_id, "node:bell:h")
        self.assertEqual(cx_step.source_node_id, "node:bell:cx")

        h_amplitudes = h_step.after.amplitudes
        self.assertIsInstance(h_amplitudes, tuple)
        self.assertNotEqual(h_amplitudes, cx_step.after.amplitudes)
        self.assertAlmostEqual(h_amplitudes[1].real, scale)

    def test_trace_capture_is_opt_in_and_preserves_legacy_simulation(self) -> None:
        program = Program(1, program_id=ProgramId("examples/opt-in.py"))
        program.h(0)
        circuit = compile_program(program)

        legacy_result = simulate(circuit)
        disabled_execution = simulate(circuit, trace=TraceCaptureOptions(enabled=False))
        runtime_result = run(program)
        traced_runtime_result = run(program, trace=TraceCaptureOptions(enabled=True))

        self.assertIsInstance(legacy_result, SimulationResult)
        self.assertIsInstance(disabled_execution, SimulationExecution)
        self.assertEqual(disabled_execution.result, legacy_result)
        self.assertIsNone(disabled_execution.trace)
        self.assertEqual(runtime_result.simulation, legacy_result)
        self.assertIsNone(runtime_result.trace)
        self.assertFalse(hasattr(runtime_result, "trace_inspection"))
        self.assertIsNotNone(traced_runtime_result.trace)
        self.assertFalse(hasattr(traced_runtime_result, "trace_inspection"))

    def test_simulator_trace_request_returns_a_public_execution_trace(self) -> None:
        circuit = compile_program(Program(1, program_id=ProgramId("examples/raw-capture.py")).h(0))

        execution = simulate(circuit, trace=TraceCaptureOptions(enabled=True))

        self.assertIsInstance(execution, SimulationExecution)
        self.assertIsNotNone(execution.trace)
        assert execution.trace is not None
        self.assertIsInstance(execution.trace, ExecutionTrace)
        captured_step = execution.trace.steps[0]
        self.assertEqual(execution.trace.initial_state.amplitudes, (1 + 0j, 0j))
        self.assertEqual(captured_step.before.amplitudes, (1 + 0j, 0j))
        self.assertIsInstance(captured_step.after.amplitudes, tuple)
        self.assertEqual(captured_step.after.amplitudes, execution.result.amplitudes)

    def test_empty_circuit_capture_contains_only_its_initial_state(self) -> None:
        result = run(
            Program(1, program_id=ProgramId("examples/empty-trace.py")),
            trace=TraceCaptureOptions(enabled=True),
        )
        trace = result.trace

        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertEqual(trace.initial_state.amplitudes, (1 + 0j, 0j))
        self.assertEqual(trace.steps, ())
        self.assertEqual(trace.final_state.amplitudes, result.simulation.amplitudes)

    def test_trace_capture_records_x_z_and_exact_measurement(self) -> None:
        program = Program(1, program_id=ProgramId("examples/measurement-trace.py"))
        program.x(0).z(0).measure(0, key="result")

        result = run(program, trace=TraceCaptureOptions(enabled=True))
        trace = result.trace

        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertEqual(
            tuple(step.operation.opcode for step in trace.steps),
            (OpCode.X, OpCode.Z, OpCode.MEASURE),
        )
        measurement_step = trace.steps[-1]
        measurement = measurement_step.measurement
        self.assertIsNotNone(measurement)
        assert measurement is not None
        self.assertEqual(measurement.kind, MeasurementRecordKind.EXACT_PROBABILITIES)
        self.assertEqual(measurement.targets, (0,))
        self.assertEqual(measurement.key, "result")
        self.assertEqual(measurement.probabilities, (0.0, 1.0))
        self.assertEqual(measurement_step.before, measurement_step.after)
        self.assertEqual(result.simulation.amplitudes, (0j, -1 + 0j))

    def test_norm_failures_report_the_operation_and_observed_value(self) -> None:
        circuit = compile_program(Program(1, program_id=ProgramId("examples/norm.py")).h(0))

        def corrupt_state(state: list[complex], operation: object) -> list[complex]:
            self.assertEqual(operation, circuit.operations[0])
            state[:] = (2 + 0j, 0j)
            return state

        with patch.object(statevector, "apply_operation", side_effect=corrupt_state):
            with self.assertRaises(SimulationNormError) as captured:
                simulate(circuit)

        error = captured.exception
        self.assertEqual(error.operation_id, circuit.operations[0].id)
        self.assertEqual(error.step_index, 0)
        self.assertEqual(error.observed_norm, 4.0)
        self.assertEqual(error.expected_norm, EXPECTED_STATE_VECTOR_NORM)
        self.assertEqual(error.tolerance, STATE_VECTOR_NORM_ABS_TOLERANCE)

    def test_norm_is_checked_after_every_unitary_operation(self) -> None:
        program = Program(2, program_id=ProgramId("examples/norm-coverage.py"))
        program.x(0).h(0).z(0).cx(0, 1).measure(0, key="result")
        circuit = compile_program(program)

        with patch.object(
            statevector,
            "_validate_state_norm",
            wraps=statevector._validate_state_norm,
        ) as validate_norm:
            simulate(circuit)

        self.assertEqual(
            [
                (call.kwargs["operation"].opcode, call.kwargs["step_index"])
                for call in validate_norm.call_args_list
            ],
            [(OpCode.X, 0), (OpCode.H, 1), (OpCode.Z, 2), (OpCode.CX, 3)],
        )


if __name__ == "__main__":
    unittest.main()
