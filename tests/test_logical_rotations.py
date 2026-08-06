from __future__ import annotations

import json
import math
import unittest

from ariadion import Program, deg, rad, run, turns
from ariadion_core import LogicalOperationId, LogicalQubitId, ProgramId
from ariadion_ir import OpCode
from ariadion_runtime import TraceCaptureOptions, inspect_execution_trace, run_logical_program
from ariadion_semantics import (
    LogicalProgram,
    LogicalQubitValue,
    LogicalRotationOperation,
    ReturnValueKind,
    ReturnValueRef,
    RotationAxis,
    ScalarReturn,
    SemanticAngle,
    SemanticAngleUnit,
)
from daidalon import compile_logical_program


class LogicalRotationTests(unittest.TestCase):
    def test_semantic_angles_convert_public_degrees_radians_and_turns(self) -> None:
        cases = (
            (deg(180), SemanticAngleUnit.DEGREES, math.pi),
            (rad(math.pi / 2), SemanticAngleUnit.RADIANS, math.pi / 2),
            (turns(0.25), SemanticAngleUnit.TURNS, math.pi / 2),
        )

        for public_angle, unit, expected_radians in cases:
            with self.subTest(unit=unit):
                angle = SemanticAngle.from_angle(public_angle)
                self.assertEqual(angle.source_unit, unit)
                self.assertAlmostEqual(angle.radians, expected_radians)
                self.assertEqual(
                    json.loads(angle.to_json()),
                    {
                        "source_value": public_angle.source_value,
                        "source_unit": unit.value,
                        "radians": public_angle.radians,
                    },
                )

    def test_x_y_and_z_logical_rotations_lower_to_matching_ir_operations(self) -> None:
        cases = (
            (RotationAxis.X, deg(180), OpCode.RX),
            (RotationAxis.Y, rad(math.pi / 2), OpCode.RY),
            (RotationAxis.Z, turns(0.25), OpCode.RZ),
        )

        for axis, public_angle, opcode in cases:
            with self.subTest(axis=axis):
                program = self._rotation_program(axis, SemanticAngle.from_angle(public_angle))
                operation = compile_logical_program(program).ir.operations[0]

                self.assertEqual(operation.opcode, opcode)
                self.assertAlmostEqual(operation.angle_radians or 0.0, public_angle.radians)
                self.assertIsNotNone(operation.angle_metadata)
                assert operation.angle_metadata is not None
                self.assertEqual(operation.angle_metadata.source_value, public_angle.source_value)
                self.assertEqual(operation.angle_metadata.source_unit, public_angle.source_unit.value)
                self.assertEqual(
                    operation.provenance.parent_logical_operation_ids,
                    (LogicalOperationId(f"logical-op:rotation:{axis.value}"),),
                )

    def test_semantic_angles_reject_non_finite_and_mismatched_canonical_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_value must be finite"):
            SemanticAngle(math.inf, SemanticAngleUnit.RADIANS, math.inf)
        with self.assertRaisesRegex(ValueError, "radians must be finite"):
            SemanticAngle(1.0, SemanticAngleUnit.RADIANS, math.inf)
        with self.assertRaisesRegex(ValueError, "must match"):
            SemanticAngle(180.0, SemanticAngleUnit.DEGREES, 0.0)

    def test_logical_rotations_require_a_declared_target(self) -> None:
        unknown_target = LogicalQubitId("logical:rotation:unknown")
        rotation = LogicalRotationOperation(
            LogicalOperationId("logical-op:rotation:unknown"),
            RotationAxis.X,
            unknown_target,
            SemanticAngle.from_angle(deg(90)),
        )

        with self.assertRaisesRegex(ValueError, "undeclared logical qubit"):
            LogicalProgram(
                ProgramId("logical:rotation:unknown"),
                "unknown-rotation",
                (),
                (rotation,),
            )

    def test_logical_rotation_serialization_is_deterministic(self) -> None:
        program = self._rotation_program(
            RotationAxis.Z,
            SemanticAngle.from_angle(deg(190)),
        )
        first = compile_logical_program(program)
        second = compile_logical_program(program)

        self.assertEqual(program.to_json(), program.to_json())
        self.assertEqual(json.loads(program.to_json()), program.to_dict())
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(
            first.ir.operations[0].to_dict()["angle_metadata"],
            {"source_value": 190.0, "source_unit": "degrees"},
        )

    def test_logical_rotation_runs_through_existing_statevector_execution(self) -> None:
        program = self._rotation_program(
            RotationAxis.X,
            SemanticAngle.from_angle(deg(180)),
        )

        execution = run_logical_program(program)

        self.assertAlmostEqual(execution.simulation.amplitudes[0].real, 0.0)
        self.assertAlmostEqual(execution.simulation.amplitudes[0].imag, 0.0)
        self.assertAlmostEqual(execution.simulation.amplitudes[1].real, 0.0)
        self.assertAlmostEqual(execution.simulation.amplitudes[1].imag, -1.0)
        self.assertIsNone(execution.classical_output_distribution)

    def test_logical_rotation_reaches_the_existing_theonoe_explanation_path(self) -> None:
        program = self._rotation_program(
            RotationAxis.Y,
            SemanticAngle.from_angle(deg(90)),
        )
        execution = run_logical_program(program, trace=TraceCaptureOptions(enabled=True))

        self.assertIsNotNone(execution.trace)
        assert execution.trace is not None
        inspection = inspect_execution_trace(execution.trace)
        explanation = inspection.steps[0].rotation_explanation
        self.assertIsNotNone(explanation)
        assert explanation is not None
        self.assertEqual(explanation.axis.value, "Y")
        self.assertAlmostEqual(explanation.angle_radians, math.pi / 2)
        self.assertEqual(execution.trace.steps[0].operation.opcode, OpCode.RY)

    def test_existing_width_based_rotations_remain_independent_of_logical_rotations(self) -> None:
        result = run(Program(1).rz(0, deg(180)))

        self.assertAlmostEqual(result.simulation.amplitudes[0].real, 0.0)
        self.assertAlmostEqual(result.simulation.amplitudes[0].imag, -1.0)

    @staticmethod
    def _rotation_program(
        axis: RotationAxis,
        angle: SemanticAngle,
    ) -> LogicalProgram:
        target = LogicalQubitValue(LogicalQubitId("logical:rotation:target"), "target")
        rotation = LogicalRotationOperation(
            LogicalOperationId(f"logical-op:rotation:{axis.value}"),
            axis,
            target.id,
            angle,
        )
        return LogicalProgram(
            ProgramId(f"logical:rotation:{axis.value}"),
            f"rotation-{axis.value}",
            (target,),
            (rotation,),
            return_shape=ScalarReturn(
                ReturnValueRef(ReturnValueKind.QUANTUM_VALUE, target.id)
            ),
        )


if __name__ == "__main__":
    unittest.main()
