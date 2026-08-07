from __future__ import annotations

import unittest

from ariadion import Bit, Program, Qubit, cx, h, quantum, run
from ariadion_core import IrOperationId, ProgramId
from ariadion_ir import CircuitIR, OpCode, Operation
from ariadion_runtime import (
    ExecutionMode,
    MeasurementRecordKind,
    ObservationExecutionKind,
    SampledLogicalRunResult,
    SampledRunResult,
    TraceCaptureOptions,
    TraceDebuggerSession,
    inspect_execution_trace,
)
from ariadion_simulator import (
    ExactResetUnsupportedError,
    SampledExecutionRequest,
    SampledTraceShotCountError,
    simulate,
)
from ariadion_cli.trace_view import render_trace_step


@quantum
def _sdk_bell() -> tuple[Bit, Bit]:
    left = Qubit()
    right = Qubit()
    h(left)
    cx(left, right)
    return left, right


def _operation(opcode: OpCode, target: int, name: str, *, control: int | None = None) -> Operation:
    return Operation(
        opcode,
        (target,),
        IrOperationId(f"sampled:{name}"),
        controls=() if control is None else (control,),
    )


def _bell_circuit() -> CircuitIR:
    return CircuitIR(
        ProgramId("sampled:bell"),
        "sampled-bell",
        2,
        (
            _operation(OpCode.H, 0, "bell:h"),
            _operation(OpCode.CX, 1, "bell:cx", control=0),
            _operation(OpCode.MEASURE, 0, "bell:measure-left"),
            _operation(OpCode.MEASURE, 1, "bell:measure-right"),
        ),
    )


class SampledExecutionTests(unittest.TestCase):
    def test_sdk_builder_run_accepts_an_explicit_sampled_execution_request(self) -> None:
        program = Program(1, name="sampled-builder")
        program.h(0)

        result = run(program, execution=SampledExecutionRequest(shots=3, seed=4))

        self.assertIsInstance(result, SampledRunResult)
        assert isinstance(result, SampledRunResult)
        self.assertEqual(len(result.simulation.shots), 3)
        self.assertEqual(result.simulation.seed, 4)

    def test_sampled_measurement_collapses_the_state_and_records_an_outcome(self) -> None:
        circuit = CircuitIR(
            ProgramId("sampled:collapse"),
            "collapse",
            1,
            (
                _operation(OpCode.H, 0, "collapse:h"),
                _operation(OpCode.MEASURE, 0, "collapse:measure"),
            ),
        )

        execution = simulate(
            circuit,
            execution=SampledExecutionRequest(shots=1, seed=7),
            trace=TraceCaptureOptions(enabled=True),
        )
        assert execution.trace is not None
        trace = execution.trace
        measurement_step = trace.steps[-1]
        measurement = measurement_step.measurement
        assert measurement is not None

        self.assertEqual(trace.metadata.mode, ExecutionMode.SAMPLED)
        self.assertEqual(trace.metadata.seed, 7)
        self.assertEqual(measurement.kind, MeasurementRecordKind.SAMPLED_OUTCOME)
        self.assertEqual(measurement.execution_kind, ObservationExecutionKind.SAMPLED_COLLAPSE)
        self.assertEqual(measurement.probabilities, ())
        self.assertIn(measurement.outcome, ((0,), (1,)))
        self.assertEqual(
            sum(abs(amplitude) > 1e-12 for amplitude in measurement_step.before.amplitudes),
            2,
        )
        self.assertEqual(
            sum(abs(amplitude) > 1e-12 for amplitude in measurement_step.after.amplitudes),
            1,
        )
        assert measurement.outcome is not None
        self.assertEqual(
            measurement_step.after.amplitudes,
            (1 + 0j, 0j) if measurement.outcome == (0,) else (0j, 1 + 0j),
        )

    def test_sampled_bell_measurements_preserve_sequential_correlation(self) -> None:
        result = simulate(
            _bell_circuit(),
            execution=SampledExecutionRequest(shots=400, seed=42),
        )
        pairs = tuple(
            tuple(outcome.outcome[0] for outcome in shot.measurement_outcomes)
            for shot in result.shots
        )

        self.assertTrue(pairs)
        self.assertTrue(all(pair in {(0, 0), (1, 1)} for pair in pairs))

    def test_sampled_mode_allows_a_gate_after_measurement(self) -> None:
        circuit = CircuitIR(
            ProgramId("sampled:mid-circuit"),
            "mid-circuit",
            2,
            (
                _operation(OpCode.H, 0, "mid:h"),
                _operation(OpCode.MEASURE, 0, "mid:measure"),
                _operation(OpCode.X, 1, "mid:x"),
            ),
        )

        result = simulate(circuit, execution=SampledExecutionRequest(shots=1, seed=3))
        shot = result.shots[0]
        outcome = shot.measurement_outcomes[0].outcome[0]
        expected_basis_index = outcome | (1 << 1)

        self.assertEqual(
            shot.result.amplitudes,
            tuple(
                1 + 0j if index == expected_basis_index else 0j
                for index in range(1 << circuit.qubit_count)
            ),
        )

    def test_sampled_builder_execution_allows_a_gate_after_measurement(self) -> None:
        program = Program(2, name="sampled-builder-mid-circuit")
        program.h(0).measure(0, key="middle").x(1)

        result = run(program, execution=SampledExecutionRequest(shots=1, seed=3))

        self.assertIsInstance(result, SampledRunResult)
        assert isinstance(result, SampledRunResult)
        final_state = result.simulation.shots[0].result.amplitudes
        self.assertEqual(sum(abs(amplitude) > 1e-12 for amplitude in final_state), 1)
        self.assertIn(
            final_state,
            (
                (0j, 0j, 1 + 0j, 0j),
                (0j, 0j, 0j, 1 + 0j),
            ),
        )

    def test_fixed_seed_repeats_identical_independent_shots(self) -> None:
        request = SampledExecutionRequest(shots=40, seed=1234)
        first = simulate(_bell_circuit(), execution=request)
        second = simulate(_bell_circuit(), execution=request)

        self.assertEqual(first, second)
        self.assertEqual(first.seed, 1234)

    def test_every_shot_reinitializes_the_complete_circuit(self) -> None:
        circuit = CircuitIR(
            ProgramId("sampled:reinitialize"),
            "reinitialize",
            1,
            (
                _operation(OpCode.X, 0, "reinitialize:x"),
                _operation(OpCode.MEASURE, 0, "reinitialize:measure"),
            ),
        )

        result = simulate(circuit, execution=SampledExecutionRequest(shots=100, seed=99))
        for shot in result.shots:
            self.assertEqual(shot.measurement_outcomes[0].outcome, (1,))

    def test_exact_mode_rejects_reset(self) -> None:
        circuit = CircuitIR(
            ProgramId("sampled:exact-reset"),
            "exact-reset",
            1,
            (_operation(OpCode.RESET, 0, "exact-reset:reset"),),
        )

        with self.assertRaises(ExactResetUnsupportedError) as captured:
            simulate(circuit)

        self.assertEqual(captured.exception.code, "A203")
        self.assertIn("does not support general reset", str(captured.exception))

    def test_reset_ir_requires_one_uncontrolled_target(self) -> None:
        self.assertFalse(hasattr(Program, "reset"))
        with self.assertRaises(ValueError):
            Operation(OpCode.RESET, (0, 1), IrOperationId("sampled:bad-reset:many"))
        with self.assertRaises(ValueError):
            Operation(
                OpCode.RESET,
                (1,),
                IrOperationId("sampled:bad-reset:control"),
                controls=(0,),
            )

    def test_sampled_reset_of_one_is_always_zero(self) -> None:
        circuit = CircuitIR(
            ProgramId("sampled:reset-one"),
            "reset-one",
            1,
            (
                _operation(OpCode.X, 0, "reset-one:x"),
                _operation(OpCode.RESET, 0, "reset-one:reset"),
                _operation(OpCode.MEASURE, 0, "reset-one:measure"),
            ),
        )

        result = simulate(circuit, execution=SampledExecutionRequest(shots=100, seed=5))
        self.assertTrue(
            all(shot.measurement_outcomes[-1].outcome == (0,) for shot in result.shots)
        )
        self.assertTrue(
            all(
                event.sampled_internal_outcome == 1
                for shot in result.shots
                for event in shot.reset_events
            )
        )

    def test_sampled_reset_of_an_entangled_qubit_discards_bell_correlation(self) -> None:
        circuit = CircuitIR(
            ProgramId("sampled:reset-entangled"),
            "reset-entangled",
            2,
            (
                _operation(OpCode.H, 0, "reset-entangled:h"),
                _operation(OpCode.CX, 1, "reset-entangled:cx", control=0),
                _operation(OpCode.RESET, 0, "reset-entangled:reset"),
                _operation(OpCode.MEASURE, 0, "reset-entangled:measure-left"),
                _operation(OpCode.MEASURE, 1, "reset-entangled:measure-right"),
            ),
        )

        result = simulate(circuit, execution=SampledExecutionRequest(shots=1000, seed=42))
        pairs = tuple(
            tuple(outcome.outcome[0] for outcome in shot.measurement_outcomes)
            for shot in result.shots
        )
        right_values = tuple(pair[1] for pair in pairs)

        self.assertTrue(all(pair[0] == 0 for pair in pairs))
        self.assertIn(0, right_values)
        self.assertIn(1, right_values)

    def test_sampled_reset_trace_has_private_reset_evidence(self) -> None:
        circuit = CircuitIR(
            ProgramId("sampled:reset-trace"),
            "reset-trace",
            1,
            (
                _operation(OpCode.X, 0, "reset-trace:x"),
                _operation(OpCode.RESET, 0, "reset-trace:reset"),
            ),
        )
        execution = simulate(
            circuit,
            execution=SampledExecutionRequest(shots=1, seed=8),
            trace=TraceCaptureOptions(enabled=True),
        )
        assert execution.trace is not None
        trace = execution.trace
        reset_step = trace.steps[1]
        assert reset_step.reset is not None

        self.assertIsNone(reset_step.measurement)
        self.assertEqual(reset_step.reset.sampled_internal_outcome, 1)
        self.assertEqual(trace.to_dict()["steps"][1]["reset"], reset_step.reset.to_dict())
        inspection = inspect_execution_trace(trace)
        self.assertEqual(inspection.steps[1].reset, reset_step.reset)
        session = TraceDebuggerSession(circuit, trace, inspection)
        rendered = render_trace_step(session.view_at(1))
        self.assertIn("Internal trajectory outcome: 1", rendered)
        self.assertIn("Applied correction: X", rendered)
        self.assertIn("Resulting target state: |0>", rendered)

    def test_multi_shot_trace_capture_rejects_one_linear_trace_for_many_trajectories(self) -> None:
        with self.assertRaises(SampledTraceShotCountError) as captured:
            simulate(
                _bell_circuit(),
                execution=SampledExecutionRequest(shots=2, seed=1),
                trace=TraceCaptureOptions(enabled=True),
            )

        self.assertEqual(captured.exception.code, "A204")
        self.assertIn("exactly one shot", str(captured.exception))

    def test_sdk_bell_exposes_empirical_counts_without_an_exact_distribution(self) -> None:
        sampled = run(
            _sdk_bell,
            execution=SampledExecutionRequest(shots=1000, seed=42),
        )
        exact = run(_sdk_bell)

        self.assertIsInstance(sampled, SampledLogicalRunResult)
        assert isinstance(sampled, SampledLogicalRunResult)
        assert sampled.classical_output is not None
        self.assertEqual(sampled.classical_output.counts[1], 0)
        self.assertEqual(sampled.classical_output.counts[2], 0)
        self.assertEqual(
            sampled.classical_output.counts[0] + sampled.classical_output.counts[3],
            1000,
        )
        self.assertEqual(sampled.classical_output.seed, 42)
        self.assertFalse(hasattr(sampled, "classical_output_distribution"))
        self.assertAlmostEqual(exact.classical_output_distribution.probabilities[0], 0.5)
        self.assertAlmostEqual(exact.classical_output_distribution.probabilities[3], 0.5)


if __name__ == "__main__":
    unittest.main()
