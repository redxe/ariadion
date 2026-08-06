from __future__ import annotations

import json
import math
import unittest

from ariadion import (
    Angle,
    AngleUnit,
    Program,
    TraceCaptureOptions,
    TraceDebuggerSession,
    deg,
    inspect_execution_trace,
    rad,
    run,
    turns,
)
from ariadion_ir import AngleMetadata, OpCode
from ariadion_visualization import render_circuit
from daidalon import CompileError, compile_program


class RotationTests(unittest.TestCase):
    def test_explicit_angle_units_preserve_source_and_canonical_values(self) -> None:
        degree_angle = deg(190)
        radians_angle = rad(2)
        turn_angle = turns(0.25)

        self.assertEqual(degree_angle.source_value, 190.0)
        self.assertEqual(degree_angle.source_unit, AngleUnit.DEGREES)
        self.assertAlmostEqual(degree_angle.radians, math.radians(190))
        self.assertEqual(radians_angle.source_unit, AngleUnit.RADIANS)
        self.assertAlmostEqual(radians_angle.radians, 2.0)
        self.assertEqual(turn_angle.source_unit, AngleUnit.TURNS)
        self.assertAlmostEqual(turn_angle.radians, math.pi / 2)
        self.assertEqual(
            json.loads(degree_angle.to_json()),
            {
                "radians": degree_angle.radians,
                "source_unit": "degrees",
                "source_value": 190.0,
            },
        )

        with self.assertRaisesRegex(ValueError, "must be finite"):
            Angle(math.inf, AngleUnit.RADIANS)
        with self.assertRaisesRegex(ValueError, "radians must be finite"):
            turns(1e308)
        with self.assertRaisesRegex(ValueError, "degrees, radians, or turns"):
            AngleMetadata(90, "grads")

    def test_compiler_rejects_bare_rotation_numbers_with_a_diagnostic(self) -> None:
        for method_name in ("rx", "ry", "rz"):
            with self.subTest(method_name=method_name):
                program = Program(1)
                getattr(program, method_name)(0, 2)

                with self.assertRaises(CompileError) as captured:
                    compile_program(program)

                self.assertEqual(
                    [(item.code, item.message) for item in captured.exception.diagnostics],
                    [
                        (
                            "A105",
                            f"{method_name.upper()} expects an angle. "
                            "Use rad(2) or deg(2).",
                        )
                    ],
                )

    def test_compiler_retains_source_angle_metadata_and_canonical_radians(self) -> None:
        program = Program(3, name="rotations")
        program.rx(0, deg(190)).ry(1, rad(2)).rz(2, turns(0.25))

        circuit = compile_program(program)
        rx, ry, rz = circuit.operations

        self.assertEqual(
            tuple(operation.opcode for operation in circuit.operations),
            (OpCode.RX, OpCode.RY, OpCode.RZ),
        )
        self.assertAlmostEqual(rx.angle_radians or 0.0, math.radians(190))
        self.assertAlmostEqual(ry.angle_radians or 0.0, 2.0)
        self.assertAlmostEqual(rz.angle_radians or 0.0, math.pi / 2)
        self.assertIsNotNone(rx.angle_metadata)
        assert rx.angle_metadata is not None
        self.assertEqual(rx.angle_metadata.source_value, 190.0)
        self.assertEqual(rx.angle_metadata.source_unit, "degrees")
        self.assertEqual(
            rx.to_dict()["angle_metadata"],
            {"source_value": 190.0, "source_unit": "degrees"},
        )
        self.assertIn("─[RX]─", render_circuit(circuit))

    def test_degree_radian_and_turn_inputs_produce_equivalent_states(self) -> None:
        degree_result = run(Program(1).rx(0, deg(180)))
        radian_result = run(Program(1).rx(0, rad(math.pi)))
        turn_result = run(Program(1).rx(0, turns(0.5)))

        for index in range(2):
            self.assertAlmostEqual(
                degree_result.simulation.amplitudes[index].real,
                radian_result.simulation.amplitudes[index].real,
            )
            self.assertAlmostEqual(
                degree_result.simulation.amplitudes[index].imag,
                radian_result.simulation.amplitudes[index].imag,
            )
            self.assertAlmostEqual(
                degree_result.simulation.amplitudes[index].real,
                turn_result.simulation.amplitudes[index].real,
            )
            self.assertAlmostEqual(
                degree_result.simulation.amplitudes[index].imag,
                turn_result.simulation.amplitudes[index].imag,
            )

    def test_rx_ry_and_rz_apply_standard_rotation_matrices(self) -> None:
        rx_result = run(Program(1).rx(0, deg(180)))
        self.assertAlmostEqual(rx_result.simulation.amplitudes[0].real, 0.0)
        self.assertAlmostEqual(rx_result.simulation.amplitudes[0].imag, 0.0)
        self.assertAlmostEqual(rx_result.simulation.amplitudes[1].real, 0.0)
        self.assertAlmostEqual(rx_result.simulation.amplitudes[1].imag, -1.0)
        self.assertEqual(rx_result.inspection.states[0].label, "|1>")
        self.assertAlmostEqual(
            rx_result.inspection.states[0].phase_radians,
            -math.pi / 2,
        )

        ry_result = run(Program(1).ry(0, rad(math.pi)))
        self.assertAlmostEqual(ry_result.simulation.amplitudes[0].real, 0.0)
        self.assertAlmostEqual(ry_result.simulation.amplitudes[1].real, 1.0)
        self.assertAlmostEqual(ry_result.simulation.amplitudes[1].imag, 0.0)

        rz_result = run(Program(1).h(0).rz(0, rad(math.pi)))
        scale = 1 / math.sqrt(2)
        self.assertAlmostEqual(rz_result.simulation.amplitudes[0].real, 0.0)
        self.assertAlmostEqual(rz_result.simulation.amplitudes[0].imag, -scale)
        self.assertAlmostEqual(rz_result.simulation.amplitudes[1].real, 0.0)
        self.assertAlmostEqual(rz_result.simulation.amplitudes[1].imag, scale)

    def test_rotation_trace_preserves_phase_and_explains_relative_phase_change(self) -> None:
        probability_result = run(
            Program(1).rx(0, deg(180)),
            trace=TraceCaptureOptions(enabled=True),
        )
        self.assertIsNotNone(probability_result.trace)
        assert probability_result.trace is not None
        probability_inspection = inspect_execution_trace(probability_result.trace)
        probability_transition = probability_inspection.steps[0].transition
        self.assertEqual(
            tuple(change.label for change in probability_transition.basis_state_changes),
            ("|0>", "|1>"),
        )
        self.assertAlmostEqual(
            probability_transition.basis_state_changes[0].probability_delta,
            -1.0,
        )
        self.assertAlmostEqual(
            probability_transition.basis_state_changes[1].probability_delta,
            1.0,
        )
        document = json.loads(
            TraceDebuggerSession(
                probability_result.ir,
                probability_result.trace,
                probability_inspection,
            ).to_json()
        )
        self.assertAlmostEqual(
            document["circuit"]["operations"][0]["angle_radians"],
            math.pi,
        )
        self.assertEqual(
            document["circuit"]["operations"][0]["angle_metadata"],
            {"source_value": 180.0, "source_unit": "degrees"},
        )

        result = run(
            Program(1).ry(0, rad(math.pi / 3)).rz(0, rad(math.pi)),
            trace=TraceCaptureOptions(enabled=True),
        )
        self.assertIsNotNone(result.trace)
        assert result.trace is not None

        trace_step = result.trace.steps[1]
        inspection_step = inspect_execution_trace(result.trace).steps[1]
        self.assertEqual(trace_step.operation.opcode, OpCode.RZ)
        self.assertAlmostEqual(trace_step.operation.angle_radians or 0.0, math.pi)
        self.assertEqual(inspection_step.angle_radians, trace_step.operation.angle_radians)
        self.assertEqual(inspection_step.angle_metadata, trace_step.operation.angle_metadata)
        self.assertEqual(
            tuple(change.label for change in inspection_step.transition.basis_state_changes),
            ("|1>",),
        )
        change = inspection_step.transition.basis_state_changes[0]
        self.assertAlmostEqual(change.probability_delta, 0.0)
        self.assertIsNotNone(change.phase_change_radians)
        assert change.phase_change_radians is not None
        self.assertAlmostEqual(abs(change.phase_change_radians), math.pi)


if __name__ == "__main__":
    unittest.main()
